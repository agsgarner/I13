# I13/agents/refinement_agent.py

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory


@dataclass
class RefinementReport:
    changed: bool
    changes: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    next_action: str = "rerun_spice"


class RefinementAgent(BaseAgent):
    def __init__(
        self,
        llm=None,
        reference_catalog=None,
        max_step_up: float = 1.5,
        max_step_down: float = 0.7,
        min_factor: float = 0.2,
        max_factor: float = 5.0,
        max_retries: int = 1,
        wait: float = 0,
    ):
        super().__init__(llm=llm, reference_catalog=reference_catalog, max_retries=max_retries, wait=wait)
        self.max_step_up = max_step_up
        self.max_step_down = max_step_down
        self.min_factor = min_factor
        self.max_factor = max_factor

    def run_agent(self, memory: SharedMemory):
        state = memory.get_full_state()
        constraints = state.get("constraints") or {}
        topo = state.get("selected_topology") or constraints.get("circuit_type")
        sizing = state.get("sizing") or {}
        sim = state.get("simulation_results") or {}
        verification = sim.get("verification_summary") or {}

        if not topo:
            report = RefinementReport(False, {}, ["No topology found"], "stop")
            memory.write("refinement_report", report.__dict__)
            memory.write("status", DesignStatus.REFINEMENT_SKIPPED)
            return state, report

        if sim.get("simulation_skipped"):
            report = RefinementReport(
                changed=False,
                changes={},
                notes=[
                    sim.get("skip_reason")
                    or "Simulation was skipped; refinement is bypassed in degraded mode."
                ],
                next_action="stop",
            )
            memory.write("refinement_report", report.__dict__)
            memory.write("status", DesignStatus.REFINEMENT_SKIPPED)
            return state, report

        if verification.get("overall_pass") is True:
            report = RefinementReport(
                changed=False,
                changes={},
                notes=["Verification summary already passes; stopping refinement to preserve convergence."],
                next_action="stop",
            )
            memory.write("refinement_report", report.__dict__)
            memory.write("status", DesignStatus.REFINEMENT_NO_CHANGE)
            return state, report

        if topo == "rc_lowpass":
            state, report = self._refine_rc_lowpass(state, constraints, sizing, sim)
        elif topo in {"rlc_lowpass_2nd_order", "rlc_highpass_2nd_order"}:
            state, report = self._refine_second_order_filter(state, constraints, sizing, sim, mode="lowhigh")
        elif topo == "rlc_bandpass_2nd_order":
            state, report = self._refine_second_order_filter(state, constraints, sizing, sim, mode="bandpass")
        elif topo in {
            "common_source_res_load",
            "source_degenerated_cs",
            "common_drain",
            "common_gate",
            "common_source_active_load",
            "diode_connected_stage",
            "cascode_amplifier",
        }:
            state, report = self._refine_common_source(state, constraints, sizing, sim)
        elif topo in {"current_mirror", "wilson_current_mirror", "cascode_current_mirror", "widlar_current_mirror"}:
            state, report = self._refine_current_mirror(state, constraints, sizing, sim)
        elif topo in {"diff_pair", "bjt_diff_pair"}:
            state, report = self._refine_diff_pair(state, constraints, sizing, sim)
        elif topo in {"two_stage_miller", "folded_cascode_opamp"}:
            state, report = self._refine_opamp_family(state, constraints, sizing, sim)
        elif topo == "gm_stage":
            state, report = self._refine_gm_stage(state, constraints, sizing, sim)
        elif topo == "bandgap_reference_core":
            state, report = self._refine_bandgap(state, constraints, sizing, sim)
        elif topo == "lc_oscillator_cross_coupled":
            state, report = self._refine_lc_oscillator(state, constraints, sizing, sim)
        elif topo == "comparator":
            state, report = self._refine_comparator(state, constraints, sizing, sim)
        elif topo == "nand2_cmos":
            state, report = self._refine_nand2(state, constraints, sizing, sim)
        elif topo == "sram6t_cell":
            state, report = self._refine_sram(state, constraints, sizing, sim)

        else:
            state, report = self._refine_from_verification_fallback(state, constraints, sizing, sim, topo)

        if (
            self.llm is not None
            and not report.changed
            and (sim.get("verification_summary") or {}).get("final_status") == "fail"
            and isinstance(state.get("sizing"), dict)
            and "stages" not in (state.get("sizing") or {})
            and state.get("status") != DesignStatus.REFINEMENT_FAILED
        ):
            state, llm_report = self._llm_refine_numeric_sizing(
                state=state,
                constraints=constraints,
                sizing=state.get("sizing") or {},
                sim=sim,
                topology=topo,
                memory=memory,
            )
            if llm_report.changed:
                report = llm_report

        memory.update({
            "sizing": state.get("sizing"),
            "refinement_report": state.get("refinement_report"),
            "status": state.get("status"),
        })
        return state, report

    def _clamp_step(self, factor: float) -> float:
        if factor > 1.0:
            return min(factor, self.max_step_up)
        return max(factor, self.max_step_down)

    def _clamp_abs(self, factor: float) -> float:
        return max(self.min_factor, min(self.max_factor, factor))

    def _device_metric(self, sim: Dict[str, Any], device: str, metric: str):
        return (((sim.get("device_metrics") or {}).get(device.lower()) or {}).get(metric.lower()))

    def _single_device_op_notes(self, sim: Dict[str, Any], device: str, vth: float):
        notes: List[str] = []
        gm = self._device_metric(sim, device, "gm")
        gds = self._device_metric(sim, device, "gds")
        current = self._device_metric(sim, device, "id")
        vgs = self._device_metric(sim, device, "vgs")
        vds = self._device_metric(sim, device, "vds")

        if gm is not None and current not in (None, 0):
            notes.append(f"{device} gm/Id ≈ {abs(float(gm) / float(current)):.3g} S/A.")
        if gm is not None and gds not in (None, 0):
            notes.append(f"{device} intrinsic gain gm/gds ≈ {abs(float(gm) / max(float(gds), 1e-18)):.3g}.")
        if vgs is not None and vds is not None:
            vov = max(float(vgs) - float(vth), 0.0)
            if float(vds) < 1.05 * vov:
                notes.append(f"{device} appears close to the triode edge in the measured operating point.")
        return notes

    def _apply_change(self, state: Dict[str, Any], changes: Dict[str, Any], notes: List[str], key: str, new: float, why: str):
        old = state["sizing"].get(key)
        if old is None:
            return
        old = float(old)
        new = float(new)
        if abs(new - old) < 1e-30:
            return
        state["sizing"][key] = new
        changes[key] = {"old": old, "new": new, "factor": (new / old) if old != 0 else None}
        notes.append(why)

    def _finish_refinement(self, state: Dict[str, Any], changes: Dict[str, Any], notes: List[str], default_note: str):
        changed = bool(changes)
        report = RefinementReport(
            changed=changed,
            changes=changes,
            notes=notes or [default_note],
            next_action="rerun_constraints_and_spice" if changed else "stop",
        )
        state["refinement_report"] = report.__dict__
        state["status"] = DesignStatus.REFINED if changed else DesignStatus.REFINEMENT_NO_CHANGE
        return state, report

    def _llm_refine_numeric_sizing(
        self,
        state: Dict[str, Any],
        constraints: Dict[str, Any],
        sizing: Dict[str, Any],
        sim: Dict[str, Any],
        topology: str,
        memory: SharedMemory = None,
    ) -> Tuple[Dict[str, Any], RefinementReport]:
        numeric_keys = []
        for key, value in sizing.items():
            if isinstance(value, (int, float)) and abs(float(value)) > 0.0:
                if key.lower() in {"supply_v", "vdd", "vin_ac", "vin_step"}:
                    continue
                numeric_keys.append(key)

        if not numeric_keys:
            return self._finish_refinement(
                state,
                {},
                ["LLM refinement skipped: no adjustable numeric sizing parameters found."],
                "No LLM refinement was applied.",
            )

        verification = sim.get("verification_summary") or {}
        failed_checks = [
            item
            for item in (verification.get("target_checks") or []) + (verification.get("analytical_checks") or [])
            if item.get("status") == "fail"
        ]

        prompt = f"""
            You are a sizing-refinement assistant for analog circuit optimization.
            Suggest multiplicative updates for existing numeric sizing keys only.

            Topology: {topology}
            Constraints: {constraints}
            Current sizing: {sizing}
            Failed checks: {failed_checks}
            Adjustable keys: {numeric_keys}

            Return JSON only:
            {{
              "updates": {{
                "<sizing_key>": <factor_between_0.5_and_1.8>
              }},
              "notes": ["short note 1", "short note 2"]
            }}
            """
        result = self.llm.generate(prompt)
        if memory is not None:
            memory.append_history(
                "llm_call",
                {
                    "agent": "RefinementAgent",
                    "task": "numeric_refinement",
                    "ok": isinstance(result, dict),
                },
            )
        if not isinstance(result, dict):
            return self._finish_refinement(
                state,
                {},
                ["LLM refinement response was not JSON; skipped."],
                "No LLM refinement was applied.",
            )

        updates = result.get("updates") or {}
        if not isinstance(updates, dict):
            updates = {}
        notes = []
        changes: Dict[str, Any] = {}

        for key, factor in updates.items():
            if key not in sizing or key not in numeric_keys:
                continue
            try:
                factor = float(factor)
            except Exception:
                continue
            factor = max(0.5, min(1.8, factor))
            factor = self._clamp_step(factor)
            old = float(sizing[key])
            new = old * factor
            if abs(new - old) <= 1e-30:
                continue
            state["sizing"][key] = new
            changes[key] = {"old": old, "new": new, "factor": factor}
            notes.append(f"LLM suggested scaling {key} by {factor:.3f}.")

        llm_notes = result.get("notes")
        if isinstance(llm_notes, list):
            notes.extend(str(item) for item in llm_notes[:3])

        if not changes:
            return self._finish_refinement(
                state,
                {},
                notes or ["LLM refinement found no safe parameter updates."],
                "No LLM refinement was applied.",
            )

        return self._finish_refinement(
            state,
            changes,
            notes,
            "LLM refinement applied numeric sizing updates.",
        )

    def _refine_rc_lowpass(
        self,
        state: Dict[str, Any],
        constraints: Dict[str, Any],
        sizing: Dict[str, Any],
        sim: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], RefinementReport]:
        target_fc = constraints.get("target_fc_hz")

        fc_used = sim.get("fc_hz")
        fc_from_ac = sim.get("fc_hz_from_ac")
        fc_formula = sim.get("fc_hz_formula")

        if target_fc is None:
            report = RefinementReport(False, {}, ["Missing target_fc_hz"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_FAILED
            return state, report

        if fc_used is None:
            report = RefinementReport(False, {}, ["Missing simulation_results.fc_hz"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_FAILED
            return state, report

        R = float(sizing.get("R_ohm", 0.0))
        C = float(sizing.get("C_f", 0.0))
        if R <= 0 or C <= 0:
            report = RefinementReport(False, {}, ["Invalid R_ohm or C_f in sizing"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_FAILED
            return state, report

        ratio = fc_used / target_fc
        if ratio <= 0:
            report = RefinementReport(False, {}, ["Bad fc ratio"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_FAILED
            return state, report

        rel_err = abs(fc_used - target_fc) / target_fc
        if rel_err < 0.05:
            notes = [
                f"Cutoff already within 5% of target ({fc_used:.6g} Hz vs {target_fc:.6g} Hz)."
            ]
            if fc_from_ac is not None:
                notes.append(f"AC-derived cutoff estimate: {fc_from_ac:.6g} Hz.")
            if fc_formula is not None:
                notes.append(f"Formula-based cutoff estimate: {fc_formula:.6g} Hz.")

            report = RefinementReport(
                changed=False,
                changes={},
                notes=notes,
                next_action="stop",
            )
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_NO_CHANGE
            return state, report

        desired_RC_scale = self._clamp_abs(ratio)
        step = self._clamp_step(desired_RC_scale)
        new_R = R * step

        state["sizing"]["R_ohm"] = new_R

        notes = [
            f"Adjusted R to move fc toward target. fc_used={fc_used:.6g} Hz, target={target_fc:.6g} Hz."
        ]
        if fc_from_ac is not None:
            notes.append(f"AC-derived cutoff estimate: {fc_from_ac:.6g} Hz.")
        if fc_formula is not None:
            notes.append(f"Formula-based cutoff estimate: {fc_formula:.6g} Hz.")

        report = RefinementReport(
            changed=True,
            changes={"R_ohm": {"old": R, "new": new_R, "factor": step}},
            notes=notes,
            next_action="rerun_constraints_and_spice",
        )
        state["refinement_report"] = report.__dict__
        state["status"] = DesignStatus.REFINED
        return state, report

    def _refine_common_source(
        self,
        state: Dict[str, Any],
        constraints: Dict[str, Any],
        sizing: Dict[str, Any],
        sim: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], RefinementReport]:
        target_gain_db = constraints.get("target_gain_db")
        target_bw_hz = constraints.get("target_bw_hz")
        power_limit_mw = constraints.get("power_limit_mw")

        gain_db = sim.get("gain_db")
        bw_hz = sim.get("bandwidth_hz")
        power_mw = sim.get("power_mw")

        W = sizing.get("W_m", sizing.get("W_n"))
        I = sizing.get("I_bias")
        RD = sizing.get("R_D", sizing.get("R_source", 1.0))

        if W is None or I is None:
            report = RefinementReport(False, {}, ["Missing sizing keys needed for OP-driven refinement"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_FAILED
            return state, report

        W = float(W)
        I = float(I)
        RD = float(RD or 1.0)

        changes: Dict[str, Any] = {}
        notes: List[str] = []
        device = "m1"
        gm_meas = self._device_metric(sim, device, "gm")
        gds_meas = self._device_metric(sim, device, "gds")
        vgs_meas = self._device_metric(sim, device, "vgs")
        vds_meas = self._device_metric(sim, device, "vds")
        vth = float(constraints.get("vth_n_v", 0.5))

        def apply_change(key: str, old: float, new: float, why: str):
            state["sizing"][key] = new
            changes[key] = {"old": old, "new": new, "factor": (new / old) if old != 0 else None}
            notes.append(why)

        if power_limit_mw is not None and power_mw is not None and power_mw > power_limit_mw:
            factor = self._clamp_abs(power_limit_mw / power_mw)
            step = self._clamp_step(factor)
            new_I = max(1e-12, I * step)
            apply_change(
                "I_bias",
                I,
                new_I,
                f"Power too high: {power_mw:.3g} mW > {power_limit_mw:.3g} mW. Reduced I_bias.",
            )
            I = new_I

        if target_gain_db is not None and gain_db is not None:
            gain_err_db = target_gain_db - gain_db

            if gain_err_db > 1.0:
                if gm_meas is not None and sizing.get("gm_target") is not None and float(gm_meas) < 0.9 * float(sizing["gm_target"]):
                    target_key = "W_m" if "W_m" in state["sizing"] else "W_n"
                    step = self._clamp_step(1.0 + min(0.5, gain_err_db / 20.0))
                    new_W = W * step
                    apply_change(
                        target_key,
                        W,
                        new_W,
                        f"Gain low and measured gm is below target. Increased {target_key} using OP data.",
                    )
                    W = new_W
                elif gds_meas is not None and float(gds_meas) > 0:
                    if "L_m" in state["sizing"]:
                        old_l = float(state["sizing"]["L_m"])
                        new_l = old_l * self._clamp_step(1.15)
                        apply_change("L_m", old_l, new_l, "Gain low with high measured gds. Increased channel length.")
                    elif "L_n" in state["sizing"]:
                        old_l = float(state["sizing"]["L_n"])
                        new_l = old_l * self._clamp_step(1.15)
                        apply_change("L_n", old_l, new_l, "Gain low with high measured gds. Increased NMOS channel length.")
                elif "R_D" in state["sizing"]:
                    step = self._clamp_step(1.10)
                    new_RD = RD * step
                    apply_change("R_D", RD, new_RD, "Gain low and OP data did not show a gm shortfall. Increased R_D.")
                    RD = new_RD

            elif gain_err_db < -1.0:
                step = self._clamp_step(1.0 - min(0.3, (-gain_err_db) / 30.0))
                target_key = "W_m" if "W_m" in state["sizing"] else "W_n"
                new_W = max(1e-9, W * step)
                apply_change(
                    target_key,
                    W,
                    new_W,
                    f"Gain high: {gain_db:.2f} dB vs target {target_gain_db:.2f} dB. Decreased {target_key}.",
                )
                W = new_W

        if vgs_meas is not None and vds_meas is not None and "I_bias" in state["sizing"]:
            measured_vov = max(float(vgs_meas) - vth, 1e-3)
            if float(vds_meas) < 1.05 * measured_vov:
                new_I = max(1e-12, I * self._clamp_step(0.85))
                apply_change(
                    "I_bias",
                    I,
                    new_I,
                    "Measured Vds is too close to Vov at the operating point. Reduced I_bias to restore saturation margin.",
                )
                I = new_I

        if target_bw_hz is not None and bw_hz is not None:
            bw_ratio = bw_hz / target_bw_hz if target_bw_hz > 0 else 1.0
            if bw_ratio < 0.8:
                step = self._clamp_step(0.85)
                new_RD = max(1e-3, RD * step)
                apply_change(
                    "R_D",
                    RD,
                    new_RD,
                    f"Bandwidth low: {bw_hz:.3g} Hz vs target {target_bw_hz:.3g} Hz. Reduced R_D.",
                )
                RD = new_RD

        notes.extend(self._single_device_op_notes(sim, device, vth))

        changed = len(changes) > 0
        if not changed:
            notes.append("No refinements applied.")

        report = RefinementReport(
            changed=changed,
            changes=changes,
            notes=notes,
            next_action="rerun_constraints_and_spice" if changed else "stop"
        )
        state["refinement_report"] = report.__dict__
        state["status"] = DesignStatus.REFINED if changed else DesignStatus.REFINEMENT_NO_CHANGE
        return state, report

    def _refine_current_mirror(self, state, constraints, sizing, sim):
        target_i = constraints.get("target_iout_a")
        sim_i = sim.get("iout_a")
        if target_i is None or sim_i is None or sim_i <= 0:
            report = RefinementReport(False, {}, ["Missing mirror current results"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_FAILED
            return state, report

        err = abs(sim_i - target_i) / target_i
        if err < 0.05:
            report = RefinementReport(False, {}, ["Mirror current already within 5%"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_NO_CHANGE
            return state, report

        factor = self._clamp_step(target_i / sim_i)
        old = float(sizing["W_out"])
        old_cas = float(sizing["W_cas"]) if "W_cas" in sizing else None
        old_aux = float(sizing["W_aux"]) if "W_aux" in sizing else None
        new = old * factor
        state["sizing"]["W_out"] = new
        if "W_cas" in state["sizing"]:
            state["sizing"]["W_cas"] = float(state["sizing"]["W_cas"]) * factor
        if "W_aux" in state["sizing"]:
            inv_factor = self._clamp_step(self._clamp_abs(1.0 / max(factor, 1e-30)))
            state["sizing"]["W_aux"] = float(state["sizing"]["W_aux"]) * inv_factor
        notes = [f"Adjusted W_out to move output current from {sim_i:.3g} A toward {target_i:.3g} A."]
        notes.extend(self._single_device_op_notes(sim, "mout", float(constraints.get("vth_n_v", 0.5))))

        extra_changes: Dict[str, Any] = {}
        if old_cas is not None:
            extra_changes["W_cas"] = {"old": old_cas, "new": float(state["sizing"]["W_cas"]), "factor": factor}
        if old_aux is not None:
            extra_changes["W_aux"] = {
                "old": old_aux,
                "new": float(state["sizing"]["W_aux"]),
                "factor": float(state["sizing"]["W_aux"]) / old_aux if old_aux != 0 else None,
            }

        report = RefinementReport(
            True,
            {"W_out": {"old": old, "new": new, "factor": factor}, **extra_changes},
            notes,
            "rerun_constraints_and_spice",
        )
        state["refinement_report"] = report.__dict__
        state["status"] = DesignStatus.REFINED
        return state, report

    def _refine_diff_pair(self, state, constraints, sizing, sim):
        target_power = constraints.get("power_limit_mw")
        gain_floor = float(constraints.get("min_gain_db", 6.0))
        gain_db = sim.get("gain_db")
        power_mw = sim.get("power_mw")

        changes = {}
        notes = []
        i_tail = float(sizing.get("I_tail", 0.0))
        r_load = float(sizing.get("R_load", 0.0))
        gm_in = self._device_metric(sim, "m1", "gm")
        vds_in = self._device_metric(sim, "m1", "vds")
        vgs_in = self._device_metric(sim, "m1", "vgs")
        vth = float(constraints.get("vth_n_v", 0.5))

        if gain_db is not None and gain_db < gain_floor and r_load > 0:
            if gm_in is not None and sizing.get("Vov_target") is not None:
                target_gm_half = 0.5 * float(sizing["I_tail"]) / max(float(sizing["Vov_target"]), 1e-12)
                if float(gm_in) < 0.9 * target_gm_half and "W_in" in state["sizing"]:
                    old_w = float(state["sizing"]["W_in"])
                    new_w = old_w * self._clamp_step(1.15)
                    state["sizing"]["W_in"] = new_w
                    changes["W_in"] = {"old": old_w, "new": new_w, "factor": new_w / old_w}
                    notes.append("Differential gain low and measured input-pair gm is below target. Increased W_in.")
                else:
                    new_r = r_load * self._clamp_step(1.15)
                    state["sizing"]["R_load"] = new_r
                    changes["R_load"] = {"old": r_load, "new": new_r, "factor": new_r / r_load}
                    notes.append(f"Differential gain below floor ({gain_db:.2f} dB < {gain_floor:.2f} dB). Increased R_load.")
            else:
                new_r = r_load * self._clamp_step(1.15)
                state["sizing"]["R_load"] = new_r
                changes["R_load"] = {"old": r_load, "new": new_r, "factor": new_r / r_load}
                notes.append(f"Differential gain below floor ({gain_db:.2f} dB < {gain_floor:.2f} dB). Increased R_load.")

        if target_power is not None and power_mw is not None and power_mw > target_power and i_tail > 0:
            factor = self._clamp_step(max(0.7, float(target_power) / float(power_mw)))
            new_i = i_tail * factor
            state["sizing"]["I_tail"] = new_i
            changes["I_tail"] = {"old": i_tail, "new": new_i, "factor": factor}
            notes.append(f"Diff-pair power too high ({power_mw:.3g} mW > {target_power:.3g} mW). Reduced I_tail.")

        if vgs_in is not None and vds_in is not None and i_tail > 0:
            measured_vov = max(float(vgs_in) - vth, 1e-3)
            if float(vds_in) < 1.05 * measured_vov:
                new_i = i_tail * self._clamp_step(0.85)
                state["sizing"]["I_tail"] = new_i
                changes["I_tail"] = {"old": i_tail, "new": new_i, "factor": new_i / i_tail}
                notes.append("Input device is too close to triode at the OP. Reduced I_tail to recover saturation.")
                i_tail = new_i

        notes.extend(self._single_device_op_notes(sim, "m1", vth))

        report = RefinementReport(
            changed=bool(changes),
            changes=changes,
            notes=notes or ["No diff-pair refinements applied."],
            next_action="rerun_constraints_and_spice" if changes else "stop",
        )
        state["refinement_report"] = report.__dict__
        state["status"] = DesignStatus.REFINED if changes else DesignStatus.REFINEMENT_NO_CHANGE
        return state, report

    def _refine_opamp_family(self, state, constraints, sizing, sim):
        changes = {}
        notes = []
        target_gain = constraints.get("target_gain_db")
        target_ugbw = constraints.get("target_ugbw_hz")
        power_limit = constraints.get("power_limit_mw")
        gain_db = sim.get("gain_db")
        ugbw = sim.get("ugbw_hz")
        power_mw = sim.get("power_mw")

        if "gm1_target_s" in sizing and target_ugbw is not None and ugbw is not None:
            ratio = float(target_ugbw) / max(float(ugbw), 1e-12)
            if abs(1.0 - ratio) > 0.20:
                old = float(sizing["gm1_target_s"])
                step = self._clamp_step(max(0.7, min(1.4, ratio)))
                new = old * step
                state["sizing"]["gm1_target_s"] = new
                changes["gm1_target_s"] = {"old": old, "new": new, "factor": step}
                notes.append(f"Adjusted gm target to move UGBW from {ugbw:.3g} Hz toward {target_ugbw:.3g} Hz.")

        if "Cc_f" in sizing and target_ugbw is not None and ugbw is not None and ugbw > 0:
            ratio = float(ugbw) / float(target_ugbw)
            if ratio > 1.35:
                old = float(sizing["Cc_f"])
                step = self._clamp_step(min(1.3, ratio))
                new = old * step
                state["sizing"]["Cc_f"] = new
                changes["Cc_f"] = {"old": old, "new": new, "factor": step}
                notes.append("Increased compensation capacitor to pull excessive UGBW back toward target.")

        if "dc_gain_linear" in sizing and target_gain is not None and gain_db is not None and gain_db < target_gain - 3.0:
            old = float(sizing["dc_gain_linear"])
            step = self._clamp_step(1.15)
            new = old * step
            state["sizing"]["dc_gain_linear"] = new
            changes["dc_gain_linear"] = {"old": old, "new": new, "factor": step}
            notes.append(f"Open-loop gain low ({gain_db:.2f} dB vs {target_gain:.2f} dB). Increased intrinsic gain target.")

        if power_limit is not None and power_mw is not None and power_mw > power_limit:
            if "I_tail" in sizing and float(sizing["I_tail"]) > 0:
                old = float(sizing["I_tail"])
                factor = self._clamp_step(max(0.7, float(power_limit) / float(power_mw)))
                new = old * factor
                state["sizing"]["I_tail"] = new
                changes["I_tail"] = {"old": old, "new": new, "factor": factor}
                notes.append("Reduced op-amp tail current to meet power limit.")
            elif "I_stage2_a" in sizing and float(sizing["I_stage2_a"]) > 0:
                old = float(sizing["I_stage2_a"])
                factor = self._clamp_step(max(0.7, float(power_limit) / float(power_mw)))
                new = old * factor
                state["sizing"]["I_stage2_a"] = new
                changes["I_stage2_a"] = {"old": old, "new": new, "factor": factor}
                notes.append("Reduced second-stage current to meet power limit.")

        report = RefinementReport(
            changed=bool(changes),
            changes=changes,
            notes=notes or ["No op-amp refinements applied."],
            next_action="rerun_constraints_and_spice" if changes else "stop",
        )
        state["refinement_report"] = report.__dict__
        state["status"] = DesignStatus.REFINED if changes else DesignStatus.REFINEMENT_NO_CHANGE
        return state, report

    def _refine_second_order_filter(self, state, constraints, sizing, sim, mode="lowhigh"):
        changes: Dict[str, Any] = {}
        notes: List[str] = []

        if mode == "bandpass":
            target_center = constraints.get("target_center_hz")
            target_bw = constraints.get("target_bw_hz")
            center = sim.get("center_hz")
            bw = sim.get("bandwidth_hz")
            l_h = float(sizing.get("L_h", 0.0))
            c_f = float(sizing.get("C_f", 0.0))
            r_ohm = float(sizing.get("R_ohm", 0.0))

            if target_center and center and c_f > 0 and l_h > 0:
                center_ratio = float(center) / max(float(target_center), 1e-30)
                if abs(1.0 - center_ratio) > 0.05:
                    c_scale = self._clamp_step(self._clamp_abs(center_ratio ** 2))
                    self._apply_change(
                        state,
                        changes,
                        notes,
                        "C_f",
                        c_f * c_scale,
                        f"Shifted band-pass center frequency from {center:.3g} Hz toward {target_center:.3g} Hz by tuning C_f.",
                    )

            if target_bw and bw and r_ohm > 0:
                bw_ratio = float(target_bw) / max(float(bw), 1e-30)
                if abs(1.0 - bw_ratio) > 0.08:
                    r_scale = self._clamp_step(self._clamp_abs(bw_ratio))
                    self._apply_change(
                        state,
                        changes,
                        notes,
                        "R_ohm",
                        r_ohm * r_scale,
                        f"Tuned R_ohm to move measured bandwidth from {bw:.3g} Hz toward {target_bw:.3g} Hz.",
                    )
            return self._finish_refinement(state, changes, notes, "Band-pass metrics are already close to target.")

        target_fc = constraints.get("target_fc_hz")
        measured_fc = sim.get("fc_hz")
        measured_q = sim.get("q_factor")
        target_q = sizing.get("q_target")
        l_h = float(sizing.get("L_h", 0.0))
        c_f = float(sizing.get("C_f", 0.0))
        r_ohm = float(sizing.get("R_ohm", 0.0))

        if target_fc and measured_fc and l_h > 0 and c_f > 0:
            ratio = float(measured_fc) / max(float(target_fc), 1e-30)
            if abs(1.0 - ratio) > 0.05:
                l_scale = self._clamp_step(self._clamp_abs(ratio ** 2))
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "L_h",
                    l_h * l_scale,
                    f"Tuned L_h to move cutoff from {measured_fc:.3g} Hz toward {target_fc:.3g} Hz.",
                )

        if target_q and measured_q and r_ohm > 0:
            q_ratio = float(measured_q) / max(float(target_q), 1e-30)
            if abs(1.0 - q_ratio) > 0.10:
                r_scale = self._clamp_step(self._clamp_abs(q_ratio))
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "R_ohm",
                    r_ohm * r_scale,
                    f"Tuned damping resistor to move Q from {measured_q:.3g} toward {target_q:.3g}.",
                )

        return self._finish_refinement(state, changes, notes, "Second-order filter metrics are already close to target.")

    def _refine_gm_stage(self, state, constraints, sizing, sim):
        changes: Dict[str, Any] = {}
        notes: List[str] = []
        target_gm = constraints.get("target_gm_s")
        gm_meas = self._device_metric(sim, "m1", "gm")
        if target_gm is None or gm_meas is None:
            return self._finish_refinement(state, changes, ["No measured gm available for gm-stage refinement."], "No gm-stage refinements applied.")

        target_gm = abs(float(target_gm))
        gm_meas = abs(float(gm_meas))
        if gm_meas <= 0:
            return self._finish_refinement(state, changes, ["Measured gm was non-positive in simulation results."], "No gm-stage refinements applied.")

        ratio = target_gm / gm_meas
        if abs(1.0 - ratio) > 0.08:
            if "W_m" in sizing:
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "W_m",
                    float(sizing["W_m"]) * self._clamp_step(self._clamp_abs(ratio)),
                    f"Adjusted W_m from measured gm={gm_meas:.3g} S toward target {target_gm:.3g} S.",
                )
            if "I_bias_a" in sizing:
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "I_bias_a",
                    max(1e-12, float(sizing["I_bias_a"]) * self._clamp_step(self._clamp_abs(ratio))),
                    "Adjusted I_bias_a alongside W_m to keep gm on target.",
                )

        return self._finish_refinement(state, changes, notes, "gm-stage already close to target gm.")

    def _refine_bandgap(self, state, constraints, sizing, sim):
        changes: Dict[str, Any] = {}
        notes: List[str] = []
        target_vref = constraints.get("target_vref_v")
        measured_vref = sim.get("vref_v")

        if target_vref is not None and measured_vref is not None and "R2_ohm" in sizing and measured_vref > 0:
            ratio = float(target_vref) / float(measured_vref)
            if abs(1.0 - ratio) > 0.015:
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "R2_ohm",
                    float(sizing["R2_ohm"]) * self._clamp_step(self._clamp_abs(ratio)),
                    f"Adjusted R2_ohm to move Vref from {measured_vref:.4g} V toward {target_vref:.4g} V.",
                )

        power_limit = constraints.get("power_limit_mw")
        power_mw = sim.get("power_mw")
        if power_limit is not None and power_mw is not None and power_mw > power_limit and "I_core" in sizing:
            factor = self._clamp_step(max(0.7, float(power_limit) / max(float(power_mw), 1e-30)))
            self._apply_change(
                state,
                changes,
                notes,
                "I_core",
                max(1e-12, float(sizing["I_core"]) * factor),
                "Reduced I_core to respect bandgap power limit.",
            )

        return self._finish_refinement(state, changes, notes, "Bandgap metrics already close to target.")

    def _refine_lc_oscillator(self, state, constraints, sizing, sim):
        changes: Dict[str, Any] = {}
        notes: List[str] = []
        target_f = constraints.get("target_osc_hz")
        measured_f = sim.get("oscillation_hz")

        if target_f is not None and measured_f is not None and measured_f > 0:
            ratio = float(measured_f) / max(float(target_f), 1e-30)
            if abs(1.0 - ratio) > 0.08:
                scale = self._clamp_step(self._clamp_abs(ratio ** 2))
                if "C_tank" in sizing:
                    self._apply_change(
                        state,
                        changes,
                        notes,
                        "C_tank",
                        max(1e-18, float(sizing["C_tank"]) * scale),
                        f"Tuned C_tank to move oscillation frequency from {measured_f:.3g} Hz toward {target_f:.3g} Hz.",
                    )
                elif "L_tank" in sizing:
                    self._apply_change(
                        state,
                        changes,
                        notes,
                        "L_tank",
                        max(1e-12, float(sizing["L_tank"]) * scale),
                        f"Tuned L_tank to move oscillation frequency from {measured_f:.3g} Hz toward {target_f:.3g} Hz.",
                    )
        elif measured_f is None and "W_pair" in sizing:
            self._apply_change(
                state,
                changes,
                notes,
                "W_pair",
                float(sizing["W_pair"]) * 1.15,
                "No clear oscillation measured. Increased cross-coupled pair width for startup margin.",
            )

        return self._finish_refinement(state, changes, notes, "Oscillator metrics already within target range.")

    def _refine_comparator(self, state, constraints, sizing, sim):
        changes: Dict[str, Any] = {}
        notes: List[str] = []
        target_delay = constraints.get("target_decision_delay_s")
        measured_delay = sim.get("decision_delay_s")
        decision_ok = sim.get("decision_correct")

        if target_delay is not None and measured_delay is not None and measured_delay > target_delay:
            speed_factor = self._clamp_step(min(1.35, float(measured_delay) / max(float(target_delay), 1e-30)))
            if "gm_latch_s" in sizing:
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "gm_latch_s",
                    float(sizing["gm_latch_s"]) * speed_factor,
                    "Increased latch gm target to reduce decision delay.",
                )
            if "tail_current_a" in sizing:
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "tail_current_a",
                    float(sizing["tail_current_a"]) * speed_factor,
                    "Increased tail current target to improve regeneration speed.",
                )

        if decision_ok is False and "gm_latch_s" in sizing:
            self._apply_change(
                state,
                changes,
                notes,
                "gm_latch_s",
                float(sizing["gm_latch_s"]) * 1.10,
                "Comparator made incorrect decision polarity. Increased latch gm target.",
            )

        return self._finish_refinement(state, changes, notes, "Comparator metrics already satisfy targets.")

    def _refine_nand2(self, state, constraints, sizing, sim):
        changes: Dict[str, Any] = {}
        notes: List[str] = []
        vdd = float(constraints.get("supply_v", 1.8))
        high = sim.get("logic_high_v")
        low = sim.get("logic_low_v")

        if high is not None and high < 0.8 * vdd and "W_p" in sizing:
            self._apply_change(
                state,
                changes,
                notes,
                "W_p",
                float(sizing["W_p"]) * 1.10,
                "Output high level is weak. Increased PMOS width for stronger pull-up.",
            )
        if low is not None and low > 0.2 * vdd and "W_n" in sizing:
            self._apply_change(
                state,
                changes,
                notes,
                "W_n",
                float(sizing["W_n"]) * 1.10,
                "Output low level is elevated. Increased NMOS width for stronger pull-down.",
            )

        return self._finish_refinement(state, changes, notes, "NAND2 transient swing already meets expected logic margins.")

    def _refine_sram(self, state, constraints, sizing, sim):
        changes: Dict[str, Any] = {}
        notes: List[str] = []
        write_ok = sim.get("write_ok")

        if write_ok is False:
            if "W_access" in sizing:
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "W_access",
                    float(sizing["W_access"]) * 1.12,
                    "Write operation failed. Increased access transistor strength.",
                )
            if "W_pulldown" in sizing:
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "W_pulldown",
                    float(sizing["W_pulldown"]) * 1.08,
                    "Write operation failed. Slightly increased pull-down strength.",
                )
            if "W_pullup" in sizing:
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "W_pullup",
                    float(sizing["W_pullup"]) * 0.96,
                    "Write operation failed. Slightly weakened pull-up devices.",
                )

        return self._finish_refinement(state, changes, notes, "SRAM write/read behavior already passes.")

    def _refine_from_verification_fallback(self, state, constraints, sizing, sim, topology):
        changes: Dict[str, Any] = {}
        notes: List[str] = []
        verification = sim.get("verification_summary") or {}
        failed_names = {
            item.get("name")
            for item in (verification.get("target_checks") or []) + (verification.get("analytical_checks") or [])
            if item.get("status") == "fail"
        }

        if not failed_names:
            return self._finish_refinement(
                state,
                changes,
                [f"No dedicated refinement rule for '{topology}', and no failed checks were reported."],
                f"No refinements applied for '{topology}'.",
            )

        if any(name in failed_names for name in {"power_mw", "plot_validation::tran_dataset"}):
            for key in ("I_bias", "I_tail", "I_stage2_a", "I_stage1_a", "tail_current_a", "I_core"):
                if key in sizing and float(sizing.get(key, 0.0)) > 0:
                    self._apply_change(
                        state,
                        changes,
                        notes,
                        key,
                        float(sizing[key]) * 0.90,
                        f"Generic fallback reduced {key} due failed power/transient checks.",
                    )

        if "gain_db" in failed_names:
            for key in ("W_m", "W_n", "W_in", "dc_gain_linear"):
                if key in sizing and float(sizing.get(key, 0.0)) > 0:
                    self._apply_change(
                        state,
                        changes,
                        notes,
                        key,
                        float(sizing[key]) * 1.08,
                        f"Generic fallback increased {key} to recover gain.",
                    )
                    break

        if any(name in failed_names for name in {"cutoff_hz", "center_hz"}) and "R_ohm" in sizing:
            measured_fc = sim.get("fc_hz")
            target_fc = constraints.get("target_fc_hz")
            if measured_fc and target_fc:
                ratio = float(measured_fc) / max(float(target_fc), 1e-30)
                self._apply_change(
                    state,
                    changes,
                    notes,
                    "R_ohm",
                    float(sizing["R_ohm"]) * self._clamp_step(self._clamp_abs(ratio)),
                    "Generic fallback tuned R_ohm from failed cutoff check.",
                )

        return self._finish_refinement(
            state,
            changes,
            notes or [f"Fallback refinement did not find safe actionable parameters for '{topology}'."],
            f"No refinements applied for '{topology}'.",
        )
