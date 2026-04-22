from dataclasses import dataclass, field
import math

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory
from core.topology_aliases import canonical_topology_key


@dataclass
class SizingReport:
    success: bool
    notes: list = field(default_factory=list)


class SizingAgent(BaseAgent):
    def _select_gm_id_target(self, constraints):
        if constraints.get("gm_id_target_s_per_a") is not None:
            return float(constraints["gm_id_target_s_per_a"])
        if float(constraints.get("power_limit_mw", 10.0) or 10.0) <= 1.0:
            return 16.0
        if float(constraints.get("target_ugbw_hz", 0.0) or 0.0) >= 10e6:
            return 8.0
        return 12.0

    def _annotate_mos_sizing(self, sizing, constraints, current_key, vov_key="Vov_target", ro_current_factor=1.0):
        current = sizing.get(current_key)
        vov = sizing.get(vov_key, constraints.get("target_vov_v"))
        lambda_1_per_v = float(constraints.get("lambda_1_per_v", 0.02))
        gm_id_target = self._select_gm_id_target(constraints)

        if current is None:
            return sizing

        current = float(current)
        sizing["gm_id_target_s_per_a"] = gm_id_target
        sizing["gm_id_est_s_per_a"] = (2.0 / max(float(vov), 1e-12)) if vov is not None else None
        sizing["inversion_hint"] = (
            "moderate" if gm_id_target >= 10.0 and gm_id_target <= 16.0
            else ("weak-leaning" if gm_id_target > 16.0 else "strong-leaning")
        )
        sizing["ro_est_ohm"] = max(
            float(constraints.get("ro_floor_ohm", 1e4)),
            1.0 / max(lambda_1_per_v * max(current * ro_current_factor, 1e-12), 1e-12),
        )
        sizing["gm_est_s"] = current * sizing["gm_id_est_s_per_a"] if sizing.get("gm_id_est_s_per_a") is not None else None
        return sizing

    def run_agent(self, memory: SharedMemory):
        state = memory.get_full_state()
        constraints = state.get("constraints", {})
        topology = state.get("selected_topology")
        topology_plan = state.get("topology_plan") or {}
        reference_summary = {"used": [], "applied_defaults": {}}

        if not topology:
            memory.write("status", DesignStatus.SIZING_FAILED)
            memory.write("sizing_report", SizingReport(False, ["No topology selected"]).__dict__)
            return state

        if topology == "composite_pipeline" or (topology_plan.get("mode") == "composite"):
            state, report, reference_summary = self._size_composite_pipeline(
                state,
                constraints,
                topology_plan,
                memory=memory,
            )
        else:
            effective_topology = canonical_topology_key(topology)
            effective_constraints, reference_summary = self._apply_reference_defaults(
                effective_topology,
                constraints,
                memory=memory,
            )
            state, report = self._size_for_topology(effective_topology, state, effective_constraints)
            if report.success and effective_topology != topology:
                report.notes.append(
                    f"Applied sizing heuristics from '{effective_topology}' for aliased topology '{topology}'."
                )
            if report.success and reference_summary.get("applied_defaults"):
                applied = ", ".join(sorted(reference_summary["applied_defaults"]))
                report.notes.append(f"Applied reference defaults for sizing: {applied}.")

        if not report.success:
            memory.write("status", DesignStatus.SIZING_FAILED)
            memory.write("sizing_report", report.__dict__)
            return state

        memory.write("sizing", state["sizing"])
        memory.write("sizing_report", report.__dict__)
        memory.write("sizing_reference_summary", reference_summary)
        memory.write("status", DesignStatus.SIZING_COMPLETE)
        return state

    def _size_for_topology(self, topology, state, constraints):
        if topology == "rc_lowpass":
            return self._size_rc_lowpass(state, constraints)
        if topology == "compensation_network_helper":
            return self._size_compensation_network_helper(state, constraints)
        if topology == "rlc_lowpass_2nd_order":
            return self._size_rlc_lowpass_2nd_order(state, constraints)
        if topology == "rlc_highpass_2nd_order":
            return self._size_rlc_highpass_2nd_order(state, constraints)
        if topology == "rlc_bandpass_2nd_order":
            return self._size_rlc_bandpass_2nd_order(state, constraints)
        if topology == "common_source_res_load":
            return self._size_common_source_res_load(state, constraints)
        if topology == "diff_pair":
            return self._size_diff_pair(state, constraints)
        if topology in {"diff_pair_current_mirror_load", "diff_pair_active_load"}:
            return self._size_diff_pair_active_load(state, constraints)
        if topology == "bjt_diff_pair":
            return self._size_bjt_diff_pair(state, constraints)
        if topology == "current_mirror":
            return self._size_current_mirror(state, constraints)
        if topology == "wilson_current_mirror":
            return self._size_wilson_current_mirror(state, constraints)
        if topology == "cascode_current_mirror":
            return self._size_cascode_current_mirror(state, constraints)
        if topology == "wide_swing_current_mirror":
            return self._size_wide_swing_current_mirror(state, constraints)
        if topology == "widlar_current_mirror":
            return self._size_widlar_current_mirror(state, constraints)
        if topology == "two_stage_miller":
            return self._size_two_stage_miller(state, constraints)
        if topology == "folded_cascode_opamp":
            return self._size_folded_cascode_opamp(state, constraints)
        if topology == "gm_stage":
            return self._size_gm_stage(state, constraints)
        if topology == "common_drain":
            return self._size_common_drain(state, constraints)
        if topology == "common_gate":
            return self._size_common_gate(state, constraints)
        if topology == "source_degenerated_cs":
            return self._size_source_degenerated_cs(state, constraints)
        if topology == "common_source_active_load":
            return self._size_common_source_active_load(state, constraints)
        if topology == "diode_connected_stage":
            return self._size_diode_connected_stage(state, constraints)
        if topology == "cascode_amplifier":
            return self._size_cascode_amplifier(state, constraints)
        if topology == "nand2_cmos":
            return self._size_nand2_cmos(state, constraints)
        if topology == "sram6t_cell":
            return self._size_sram6t_cell(state, constraints)
        if topology == "lc_oscillator_cross_coupled":
            return self._size_lc_oscillator(state, constraints)
        if topology == "bandgap_reference_core":
            return self._size_bandgap_reference(state, constraints)
        if topology in {"comparator", "latched_comparator", "static_comparator"}:
            return self._size_comparator(state, constraints)
        if topology == "transimpedance_frontend":
            return self._size_transimpedance_frontend(state, constraints)
        if topology == "current_sense_amp_helper":
            return self._size_current_sense_amp_helper(state, constraints)
        return state, SizingReport(False, [f"Sizing not implemented for {topology}"])

    def _size_composite_pipeline(self, state, constraints, topology_plan, memory: SharedMemory = None):
        stages = (topology_plan or {}).get("stages") or []
        if len(stages) < 2:
            return state, SizingReport(False, ["Composite pipeline requires at least two valid stages."]), {"used": [], "applied_defaults": {}}

        llm_hints = self._llm_composite_sizing_hints(stages, constraints, memory=memory)
        llm_stage_constraints = llm_hints.get("stage_constraints") or []
        llm_notes = llm_hints.get("notes") or []

        composite_stages = []
        notes = list(llm_notes)
        estimated_gain_db = 0.0
        used_hits = []
        applied_defaults = {}

        for idx, stage in enumerate(stages):
            topology = stage.get("topology")
            if not topology:
                return state, SizingReport(False, [f"Stage {idx + 1} is missing topology."]), {"used": used_hits, "applied_defaults": applied_defaults}

            stage_specific_constraints = stage.get("constraints") or {}
            stage_constraints = dict(constraints)
            stage_constraints.update(stage_specific_constraints)
            if idx < len(llm_stage_constraints) and isinstance(llm_stage_constraints[idx], dict):
                stage_constraints.update(llm_stage_constraints[idx])
            stage_constraints, stage_reference_summary = self._apply_reference_defaults(
                topology,
                stage_constraints,
                memory=memory,
            )
            used_hits.extend(stage_reference_summary.get("used") or [])
            for key, value in (stage_reference_summary.get("applied_defaults") or {}).items():
                applied_defaults[f"{stage.get('name') or f'stage{idx + 1}'}::{key}"] = value

            stage_state = {
                "case_metadata": state.get("case_metadata") or {},
                "sizing": {},
            }
            stage_state, stage_report = self._size_for_topology(topology, stage_state, stage_constraints)
            if not stage_report.success:
                return state, SizingReport(
                    False,
                    [f"Stage {idx + 1} sizing failed for topology '{topology}': {', '.join(stage_report.notes)}"],
                ), {"used": used_hits, "applied_defaults": applied_defaults}
            if stage_reference_summary.get("applied_defaults"):
                stage_report.notes.append(
                    "Applied reference defaults: "
                    + ", ".join(sorted(stage_reference_summary["applied_defaults"]))
                )

            stage_sizing = stage_state.get("sizing") or {}
            if stage_specific_constraints.get("target_gain_db") is not None:
                estimated_gain_db += float(stage_specific_constraints.get("target_gain_db"))
            elif stage_sizing.get("gm_target") is not None and stage_sizing.get("R_D") is not None:
                gain_vv = max(float(stage_sizing["gm_target"]) * float(stage_sizing["R_D"]), 1e-12)
                estimated_gain_db += 20.0 * math.log10(gain_vv)

            composite_stages.append(
                {
                    "name": stage.get("name") or f"stage{idx + 1}",
                    "role": stage.get("role") or f"stage_{idx + 1}",
                    "topology": topology,
                    "constraints": stage_constraints,
                    "sizing": stage_sizing,
                    "notes": list(stage_report.notes),
                }
            )
            notes.append(f"Stage {idx + 1} ({topology}) sized successfully.")

        state["sizing"] = {
            "stages": composite_stages,
            "interstage_res_ohm": float(llm_hints.get("interstage_res_ohm", constraints.get("interstage_res_ohm", 2000.0))),
            "interstage_cap_f": float(llm_hints.get("interstage_cap_f", constraints.get("interstage_cap_f", 0.5e-12))),
            "estimated_total_gain_db": estimated_gain_db,
            "stage_count": len(composite_stages),
        }
        notes.append(
            f"Composite sizing complete with {len(composite_stages)} stages "
            f"(estimated total gain ~ {estimated_gain_db:.2f} dB)."
        )
        return state, SizingReport(True, notes), {"used": used_hits, "applied_defaults": applied_defaults}

    def _apply_reference_defaults(self, topology, constraints, memory: SharedMemory = None):
        hits = []
        if memory is not None:
            hits = self.retrieve_references(
                memory,
                query=f"{topology} sizing defaults",
                topologies=[topology],
                content_types=[
                    "template",
                    "device_selection_heuristic",
                    "cookbook_circuit",
                    "design_equation",
                ],
                limit=6,
                trace_label=f"sizing_defaults::{topology}",
            )

        merged = dict(constraints)
        applied_defaults = {}
        for hit in hits:
            data = hit.get("data") or {}
            for bucket in ("default_constraints", "heuristic_defaults", "constraint_defaults"):
                defaults = data.get(bucket) or {}
                if not isinstance(defaults, dict):
                    continue
                for key, value in defaults.items():
                    if merged.get(key) is None:
                        merged[key] = value
                        applied_defaults[key] = {
                            "value": value,
                            "source": hit.get("id"),
                        }
        return merged, {"used": hits, "applied_defaults": applied_defaults}

    def _llm_composite_sizing_hints(self, stages, constraints, memory: SharedMemory = None):
        if self.llm is None:
            return {}
        if constraints.get("enable_llm_stage_sizing", True) is False:
            return {}

        prompt = f"""
            You are allocating first-pass sizing intent for a cascaded analog pipeline.
            Keep suggestions physically plausible and modest.

            Stage plan:
            {stages}

            Global constraints:
            {constraints}

            Return JSON only:
            {{
              "stage_constraints": [
                {{"target_gain_db": 12.0, "target_bw_hz": 3000000.0}}
              ],
              "interstage_res_ohm": 2000.0,
              "interstage_cap_f": 5e-13,
              "notes": ["short note"]
            }}

            Rules:
            - stage_constraints length must be <= number of stages
            - only include numeric values
            - keep updates conservative (within about 0.5x to 2.0x of global targets)
            """
        result = self.llm.generate(prompt)
        if memory is not None:
            memory.append_history(
                "llm_call",
                {
                    "agent": "SizingAgent",
                    "task": "composite_sizing_hints",
                    "ok": isinstance(result, dict),
                },
            )
        if not isinstance(result, dict):
            return {}

        stage_constraints = []
        raw_stage_constraints = result.get("stage_constraints")
        if isinstance(raw_stage_constraints, list):
            for item in raw_stage_constraints[: len(stages)]:
                if not isinstance(item, dict):
                    stage_constraints.append({})
                    continue
                parsed = {}
                for key, value in item.items():
                    if isinstance(value, (int, float)):
                        parsed[str(key)] = float(value)
                stage_constraints.append(parsed)

        hints = {"stage_constraints": stage_constraints}
        for key in ("interstage_res_ohm", "interstage_cap_f"):
            value = result.get(key)
            if isinstance(value, (int, float)) and float(value) > 0:
                hints[key] = float(value)
        if isinstance(result.get("notes"), list):
            hints["notes"] = [str(item) for item in result.get("notes")[:3]]
        return hints

    def _size_rc_lowpass(self, state, constraints):
        fc = float(constraints.get("target_fc_hz", 1e3))
        C = float(constraints.get("fixed_cap_f", 10e-9))
        R = 1.0 / (2.0 * math.pi * fc * C)

        state["sizing"] = {
            "R_ohm": R,
            "C_f": C
        }
        return state, SizingReport(True, ["RC low-pass sized from target cutoff"])

    def _size_compensation_network_helper(self, state, constraints):
        fc = float(constraints.get("target_fc_hz", 200e3))
        cc = float(constraints.get("Cc_f", constraints.get("fixed_cap_f", 2e-12)))
        rz = 1.0 / (2.0 * math.pi * max(fc, 1e-3) * max(cc, 1e-18))
        state["sizing"] = {
            "R_ohm": rz,
            "C_f": cc,
            "Rz_ohm": rz,
            "Cc_f": cc,
            "target_fc_hz": fc,
        }
        return state, SizingReport(
            True,
            ["Compensation helper sized from target pole/zero break frequency."],
        )

    def _filter_q_from_constraints(self, constraints, default_family="butterworth"):
        if constraints.get("q_target") is not None:
            return float(constraints.get("q_target"))
        if constraints.get("damping_ratio") is not None:
            damping = max(float(constraints.get("damping_ratio")), 1e-9)
            return 1.0 / (2.0 * damping)

        family = (constraints.get("response_family") or default_family).strip().lower()
        family_q = {
            "butterworth": 1.0 / math.sqrt(2.0),
            "bessel": 1.0 / math.sqrt(3.0),
            "chebyshev": 0.95,
            "chebyshev_0p5db": 0.86,
            "chebyshev_1db": 0.95,
        }
        return family_q.get(family, 1.0 / math.sqrt(2.0))

    def _base_filter_metadata(self, constraints, q_target, order=2):
        damping = 1.0 / max(2.0 * q_target, 1e-12)
        response_family = (constraints.get("response_family") or "butterworth").strip().lower()
        return {
            "filter_order": int(constraints.get("filter_order", order)),
            "response_family": response_family,
            "q_target": q_target,
            "damping_ratio": damping,
            "rolloff_db_per_dec": 20.0 * max(int(constraints.get("filter_order", order)), 1),
            "source_res_ohm": float(constraints.get("source_res_ohm", 50.0)),
            "load_res_ohm": float(constraints.get("load_res_ohm", 10000.0)),
            "passband_gain_db": float(constraints.get("passband_gain_db", 0.0)),
        }

    def _size_rlc_lowpass_2nd_order(self, state, constraints):
        fc = float(constraints.get("target_fc_hz", 5e3))
        c_f = float(constraints.get("fixed_cap_f", 10e-9))
        q_target = max(self._filter_q_from_constraints(constraints), 0.25)
        w0 = 2.0 * math.pi * fc
        l_h = 1.0 / (max(w0**2 * c_f, 1e-30))
        r_ohm = math.sqrt(max(l_h / c_f, 1e-30)) / q_target

        state["sizing"] = {
            "R_ohm": r_ohm,
            "L_h": l_h,
            "C_f": c_f,
            "target_fc_hz": fc,
            **self._base_filter_metadata(constraints, q_target),
        }
        return state, SizingReport(
            True,
            [
                "Second-order RLC low-pass section sized from cutoff and response family.",
                f"Estimated Q ≈ {q_target:.3f}.",
                f"Estimated damping ratio ≈ {state['sizing']['damping_ratio']:.3f}.",
            ],
        )

    def _size_rlc_highpass_2nd_order(self, state, constraints):
        fc = float(constraints.get("target_fc_hz", 2e3))
        c_f = float(constraints.get("fixed_cap_f", 4.7e-9))
        q_target = max(self._filter_q_from_constraints(constraints, default_family="bessel"), 0.25)
        w0 = 2.0 * math.pi * fc
        l_h = 1.0 / (max(w0**2 * c_f, 1e-30))
        r_ohm = math.sqrt(max(l_h / c_f, 1e-30)) / q_target

        state["sizing"] = {
            "R_ohm": r_ohm,
            "L_h": l_h,
            "C_f": c_f,
            "target_fc_hz": fc,
            **self._base_filter_metadata(constraints, q_target),
        }
        return state, SizingReport(
            True,
            [
                "Second-order RLC high-pass section sized from cutoff and damping target.",
                f"Estimated Q ≈ {q_target:.3f}.",
                f"Estimated damping ratio ≈ {state['sizing']['damping_ratio']:.3f}.",
            ],
        )

    def _size_rlc_bandpass_2nd_order(self, state, constraints):
        center_hz = float(constraints.get("target_center_hz", 20e3))
        bw_hz = float(constraints.get("target_bw_hz", max(center_hz / 5.0, 1.0)))
        l_h = float(constraints.get("fixed_ind_h", 10e-3))
        q_target = max(center_hz / max(bw_hz, 1e-12), 0.5)
        w0 = 2.0 * math.pi * center_hz
        c_f = 1.0 / (max(w0**2 * l_h, 1e-30))
        r_ohm = w0 * l_h / q_target

        state["sizing"] = {
            "R_ohm": r_ohm,
            "L_h": l_h,
            "C_f": c_f,
            "target_center_hz": center_hz,
            "target_bw_hz": bw_hz,
            **self._base_filter_metadata(constraints, q_target),
        }
        state["sizing"]["rolloff_db_per_dec"] = 20.0
        return state, SizingReport(
            True,
            [
                "Second-order RLC band-pass section sized from center frequency and bandwidth.",
                f"Estimated Q ≈ {q_target:.3f}.",
                f"Estimated series resistance ≈ {r_ohm:.3f} ohm.",
            ],
        )

    def _size_common_source_res_load(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        gain_db = float(constraints.get("target_gain_db", 20.0))
        target_vov_v = float(constraints.get("target_vov_v", 0.2))
        mu_cox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L_m = float(constraints.get("L_m", 180e-9))

        gain_linear = 10 ** (gain_db / 20.0)

        # Choose a reasonable DC output bias near midrail for headroom
        vout_q = float(constraints.get("target_vout_q_v", 0.5 * vdd))

        # Start with a practical resistor guess, then solve current from headroom
        RD = float(constraints.get("R_D_initial", 5000.0))

        # DC current allowed by chosen output quiescent point
        I_bias = max(1e-6, (vdd - vout_q) / RD)

        # Small-signal gm needed for target gain magnitude |Av| ~= gm * RD
        gm_target = gain_linear / RD

        # Check whether chosen I and target Vov support that gm
        # gm ~= 2*Id / Vov  => required Id = gm*Vov/2
        I_required_for_gain = gm_target * target_vov_v / 2.0

        # Use the larger of the two currents:
        # - current needed for the target gain
        # - current set by chosen quiescent point
        I_bias = max(I_bias, I_required_for_gain)

        # Recompute RD so output stays near chosen quiescent voltage
        RD = max(100.0, (vdd - vout_q) / I_bias)

        # Recompute gm target from final RD
        gm_target = gain_linear / RD

        # From square-law first-pass sizing:
        # Id = 0.5 * muCox * (W/L) * Vov^2
        W_over_L = max(0.5, (2.0 * I_bias) / (mu_cox * target_vov_v**2))
        W_m = W_over_L * L_m

        state["sizing"] = {
            "W_m": W_m,
            "L_m": L_m,
            "R_D": RD,
            "I_bias": I_bias,
            "gm_target": gm_target,
            "Vov_target": target_vov_v,
            "Vout_q_target": vout_q
        }
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_bias")

        return state, SizingReport(
            True,
            [
                "Common-source sizing adjusted for gain and DC headroom.",
                f"Chosen Vout_q ≈ {vout_q:.3f} V.",
                f"Estimated I_bias ≈ {I_bias:.3e} A.",
                f"Estimated R_D ≈ {RD:.3f} ohm.",
            ]
        )

    def _size_diff_pair(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        power_limit_mw = float(constraints.get("power_limit_mw", 2.0))
        Vov = float(constraints.get("target_vov_v", 0.2))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L_in = float(constraints.get("L_in_m", 180e-9))
        L_tail = float(constraints.get("L_tail_m", 180e-9))
        R_load = float(constraints.get("R_load_ohm", 5000.0))

        I_tail = max(1e-6, (power_limit_mw / 1000.0) / vdd)

        W_over_L_in = max(0.5, 2.0 * (I_tail / 2.0) / (muCox * Vov**2))
        W_over_L_tail = max(0.5, 2.0 * I_tail / (muCox * Vov**2))

        state["sizing"] = {
            "W_in": W_over_L_in * L_in,
            "L_in": L_in,
            "W_tail": W_over_L_tail * L_tail,
            "L_tail": L_tail,
            "I_tail": I_tail,
            "R_load": R_load,
            "Vov_target": Vov
        }
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_tail", ro_current_factor=0.5)
        return state, SizingReport(True, ["MOS differential pair initial sizing complete"])

    def _size_diff_pair_active_load(self, state, constraints):
        state, report = self._size_diff_pair(state, constraints)
        vov_p = float(constraints.get("target_vov_p_v", 0.22))
        mu_p = float(constraints.get("mu_cox_p_a_per_v2", 80e-6))
        l_load = float(constraints.get("L_load_m", state["sizing"].get("L_in", 180e-9)))
        i_half = 0.5 * float(state["sizing"].get("I_tail", 40e-6))
        w_load = max(0.5, 2.0 * max(i_half, 1e-9) / max(mu_p * vov_p**2, 1e-30)) * l_load
        state["sizing"]["W_load"] = w_load
        state["sizing"]["L_load"] = l_load
        state["sizing"]["Vov_load_target"] = vov_p
        report.notes.append("Added PMOS active-load sizing for differential pair front-end.")
        return state, report

    def _size_bjt_diff_pair(self, state, constraints):
        I_tail = float(constraints.get("tail_current_a", 200e-6))
        beta = float(constraints.get("beta", 100))
        Rc = float(constraints.get("collector_res_ohm", 10000))
        Vt = 0.02585

        Ic_each = I_tail / 2.0
        gm = Ic_each / Vt
        re_small = 1.0 / gm

        state["sizing"] = {
            "I_tail": I_tail,
            "Ic_each": Ic_each,
            "beta": beta,
            "R_C": Rc,
            "gm_each": gm,
            "r_e_small_signal": re_small,
            "r_pi_est": beta / gm
        }
        return state, SizingReport(True, ["BJT differential pair sized from tail current"])

    def _size_current_mirror(self, state, constraints):
        I_out = float(constraints.get("target_iout_a", 100e-6))
        ratio = float(constraints.get("mirror_ratio", 1.0))
        Vov = float(constraints.get("target_vov_v", 0.2))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L_ref = float(constraints.get("L_ref_m", 180e-9))
        L_out = float(constraints.get("L_out_m", 180e-9))

        I_ref = I_out / max(ratio, 1e-9)

        W_over_L_ref = max(0.5, 2.0 * I_ref / (muCox * Vov**2))
        W_over_L_out = max(0.5, 2.0 * I_out / (muCox * Vov**2))

        state["sizing"] = {
            "W_ref": W_over_L_ref * L_ref,
            "L_ref": L_ref,
            "W_out": W_over_L_out * L_out,
            "L_out": L_out,
            "I_ref": I_ref,
            "I_out_target": I_out,
            "mirror_ratio": ratio,
            "Vov_target": Vov,
            "compliance_v_est": Vov
        }
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_ref")
        return state, SizingReport(True, ["Current mirror sized from target current and ratio"])

    def _size_wilson_current_mirror(self, state, constraints):
        state, report = self._size_current_mirror(state, constraints)
        state["sizing"]["W_aux"] = state["sizing"]["W_ref"]
        state["sizing"]["L_aux"] = state["sizing"]["L_ref"]
        report.notes.append("Wilson mirror adds a third matched feedback device for improved current-copy accuracy.")
        return state, report

    def _size_cascode_current_mirror(self, state, constraints):
        state, report = self._size_current_mirror(state, constraints)
        l_cas = float(constraints.get("L_cas_m", state["sizing"]["L_ref"]))
        state["sizing"]["W_cas"] = 1.2 * state["sizing"]["W_ref"]
        state["sizing"]["L_cas"] = l_cas
        state["sizing"]["Vbias_cas"] = float(constraints.get("Vbias_cas_v", 0.9))
        report.notes.append("Cascode mirror adds cascode device sizing for higher output resistance.")
        return state, report

    def _size_wide_swing_current_mirror(self, state, constraints):
        state, report = self._size_cascode_current_mirror(state, constraints)
        state["sizing"]["W_cas"] = 0.9 * float(state["sizing"]["W_cas"])
        state["sizing"]["Vbias_cas"] = float(constraints.get("Vbias_cas_v", 0.72))
        state["sizing"]["compliance_v_est"] = max(
            float(constraints.get("compliance_v", 0.45)),
            2.0 * float(constraints.get("target_vov_v", 0.15)),
        )
        report.notes.append("Wide-swing mirror variant biases cascodes for lower compliance headroom.")
        return state, report

    def _size_widlar_current_mirror(self, state, constraints):
        state, report = self._size_current_mirror(state, constraints)
        target_i = float(constraints.get("target_iout_a", 20e-6))
        vt = float(constraints.get("thermal_voltage_v", 0.02585))
        beta = float(constraints.get("widlar_beta", 1.0))
        state["sizing"]["R_emitter_deg_ohm"] = max(100.0, vt * math.log(max(beta, 1.0001) + 1.0) / max(target_i, 1e-12))
        report.notes.append("Widlar mirror adds source degeneration to realize lower output current.")
        return state, report

    def _size_two_stage_miller(self, state, constraints):
        case_meta = state.get("case_metadata") or {}
        if case_meta.get("demo_model") in {"behavioral_opamp_proxy", "native_telescopic"}:
            return self._size_telescopic_cascode_opamp(state, constraints)

        ugbw = float(constraints.get("target_ugbw_hz", 1e6))
        load_cap = float(constraints.get("load_cap_f", 1e-12))
        slew_rate = float(constraints.get("target_slew_v_per_us", 1.0)) * 1e6
        supply_v = float(constraints.get("supply_v", 1.8))

        Cc = max(0.2 * load_cap, 0.5e-12)
        gm1 = 2.0 * math.pi * ugbw * Cc
        I2 = slew_rate * Cc
        I1 = max(I2 / 10.0, 10e-6)
        target_gain_db = float(constraints.get("target_gain_db", 60.0))
        stage_gain_linear = math.sqrt(max(10 ** (target_gain_db / 20.0), 1.0))

        state["sizing"] = {
            "Cc_f": Cc,
            "gm1_target_s": gm1,
            "I_stage1_a": I1,
            "I_stage2_a": I2,
            "supply_v": supply_v,
            "stage_gain_linear": stage_gain_linear,
        }
        state["sizing"]["gm_id_target_s_per_a"] = self._select_gm_id_target(constraints)
        return state, SizingReport(True, ["Two-stage Miller op-amp initial sizing from UGBW and slew-rate"])

    def _size_telescopic_cascode_opamp(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        ugbw = float(constraints.get("target_ugbw_hz", 12e6))
        cload = float(constraints.get("load_cap_f", 1e-12))
        power_limit_mw = float(constraints.get("power_limit_mw", 2.0))
        target_vov_n = float(constraints.get("target_vov_v", 0.16))
        target_vov_p = float(constraints.get("target_vov_p_v", 0.18))
        mu_n = float(constraints.get("mu_cox_a_per_v2", 200e-6))
        mu_p = float(constraints.get("mu_cox_p_a_per_v2", 80e-6))
        l_n = float(constraints.get("L_in_m", 1.0e-6))
        l_p = float(constraints.get("L_load_m", 1.0e-6))

        gm_in = max(2.0 * math.pi * ugbw * cload, 0.5e-3)
        i_tail = min(power_limit_mw / 1000.0 / max(vdd, 1e-9), gm_in * target_vov_n)
        i_tail = max(i_tail, 40e-6)
        id_half = 0.5 * i_tail

        w_in = max(0.5, 2.0 * id_half / max(mu_n * target_vov_n**2, 1e-30)) * l_n
        w_cas_n = 1.6 * w_in
        w_load = max(0.5, 2.0 * id_half / max(mu_p * target_vov_p**2, 1e-30)) * l_p
        w_cas_p = 1.6 * w_load

        state["sizing"] = {
            "I_tail": i_tail,
            "gm1_target_s": gm_in,
            "W_in": w_in,
            "L_in": l_n,
            "W_cas_n": w_cas_n,
            "L_cas_n": l_n,
            "W_load_p": w_load,
            "L_load_p": l_p,
            "Vbias_n": min(vdd - 0.2, 1.15),
            "Vbias_p": max(0.7, 1.0),
            "Vicm_v": float(constraints.get("vin_cm_dc", 0.9)),
            "power_target_mw": 1000.0 * vdd * i_tail,
        }
        state["sizing"]["gm_id_target_s_per_a"] = self._select_gm_id_target(constraints)
        return state, SizingReport(
            True,
            [
                "Telescopic cascode OTA sized from UGBW, load capacitance, and power limit.",
                f"Tail current target ≈ {i_tail:.3e} A.",
                f"Input-pair gm target ≈ {gm_in:.3e} S.",
            ],
        )

    def _size_folded_cascode_opamp(self, state, constraints):
        target_ugbw = float(constraints.get("target_ugbw_hz", 20e6))
        target_gain_db = float(constraints.get("target_gain_db", 65.0))
        load_cap = float(constraints.get("load_cap_f", 1e-12))
        vdd = float(constraints.get("supply_v", 1.8))
        power_limit_mw = float(constraints.get("power_limit_mw", 2.0))
        gm1 = max(2.0 * math.pi * target_ugbw * load_cap, 0.5e-3)
        max_bias_a = power_limit_mw / 1000.0 / max(vdd, 1e-9)
        i_tail = max(40e-6, min(max_bias_a, 0.4 * gm1))
        dc_gain_linear = max(10 ** (target_gain_db / 20.0), 100.0)
        r_out = dc_gain_linear / max(gm1, 1e-12)
        state["sizing"] = {
            "gm1_target_s": gm1,
            "I_tail": i_tail,
            "R_out_ohm": r_out,
            "dc_gain_linear": dc_gain_linear,
            "Vcm_ref": float(constraints.get("vin_cm_dc", 0.9)),
            "output_cm_v": float(constraints.get("target_vout_q_v", 0.9)),
        }
        state["sizing"]["gm_id_target_s_per_a"] = self._select_gm_id_target(constraints)
        return state, SizingReport(
            True,
            [
                "Folded-cascode OTA proxy sized from target UGBW, gain, load capacitance, and power.",
                f"gm target ≈ {gm1:.3e} S.",
                f"Estimated output resistance ≈ {r_out:.3e} ohm.",
            ],
        )

    def _size_gm_stage(self, state, constraints):
        gm_target = float(constraints.get("target_gm_s", 1e-3))
        Vov = float(constraints.get("target_vov_v", 0.2))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L = float(constraints.get("L_m", 180e-9))

        Id = gm_target * Vov / 2.0
        W_over_L = max(0.5, 2.0 * Id / (muCox * Vov**2))
        W = W_over_L * L

        state["sizing"] = {
            "gm_target_s": gm_target,
            "I_bias_a": Id,
            "W_m": W,
            "L_m": L,
            "Vov_target_v": Vov
        }
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_bias_a", vov_key="Vov_target_v")
        return state, SizingReport(True, ["GM stage sized from gm and Vov"])

    def _size_common_drain(self, state, constraints):
        gm_target = float(constraints.get("target_gm_s", 2e-3))
        Vov = float(constraints.get("target_vov_v", 0.18))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L = float(constraints.get("L_m", 180e-9))
        vdd = float(constraints.get("supply_v", 1.8))
        vth = float(constraints.get("vth_n_v", 0.5))
        target_vout_q = float(constraints.get("target_vout_q_v", 0.4 * vdd))
        Id = max(20e-6, gm_target * Vov / 2.0)
        W_over_L = max(0.5, 2.0 * Id / (muCox * Vov**2))
        state["sizing"] = {
            "W_m": W_over_L * L,
            "L_m": L,
            "I_bias": Id,
            "R_source": max(200.0, target_vout_q / Id),
            "Vbias": min(vdd - 0.2, 0.7 + Vov),
            "gm_target": gm_target,
            "Vout_q_target": target_vout_q,
            "Vin_bias": min(vdd - 0.05, target_vout_q + vth + Vov),
        }
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_bias")
        return state, SizingReport(True, ["Common-drain source follower initial sizing complete"])

    def _size_common_gate(self, state, constraints):
        gm_target = float(constraints.get("target_gm_s", 1.5e-3))
        Vov = float(constraints.get("target_vov_v", 0.2))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L = float(constraints.get("L_m", 180e-9))
        vdd = float(constraints.get("supply_v", 1.8))
        Id = max(20e-6, gm_target * Vov / 2.0)
        W_over_L = max(0.5, 2.0 * Id / (muCox * Vov**2))
        rd = max(1e3, float(constraints.get("R_D_ohm", 0.5 * vdd / Id)))
        state["sizing"] = {
            "W_m": W_over_L * L,
            "L_m": L,
            "I_bias": Id,
            "R_D": rd,
            "Vbias": min(vdd - 0.2, 1.0),
            "gm_target": gm_target,
        }
        state["sizing"]["Vov_target"] = Vov
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_bias")
        return state, SizingReport(True, ["Common-gate initial sizing complete"])

    def _size_source_degenerated_cs(self, state, constraints):
        state, report = self._size_common_source_res_load(state, constraints)
        gm = state["sizing"]["gm_target"]
        gain_db = float(constraints.get("target_gain_db", 12.0))
        gain_lin = max(1.0, 10 ** (gain_db / 20.0))
        rs = max(10.0, (max(gm, 1e-9) / gain_lin - 1.0) / max(gm, 1e-9))
        state["sizing"]["R_S"] = max(10.0, rs)
        report.notes.append("Added source degeneration resistor for gain linearization.")
        return state, report

    def _size_transimpedance_frontend(self, state, constraints):
        target_bw = float(constraints.get("target_bw_hz", 500e3))
        z_target = constraints.get("target_transimpedance_ohm")
        if z_target is None:
            z_target = 10 ** (float(constraints.get("target_gain_db", 70.0)) / 20.0)
        z_target = float(z_target)
        c_feedback = max(0.2e-12, 1.0 / (2.0 * math.pi * max(target_bw, 1.0) * max(z_target, 1e-3)))
        gm_input = max(0.5e-3, 2.0 * math.pi * target_bw * c_feedback)
        vdd = float(constraints.get("supply_v", 1.8))
        power_limit = float(constraints.get("power_limit_mw", 2.0))
        ibias = max(20e-6, min(power_limit / 1000.0 / max(vdd, 1e-9), gm_input * 0.12))
        state["sizing"] = {
            "R_feedback_ohm": z_target,
            "C_feedback_f": c_feedback,
            "gm_input_s": gm_input,
            "I_bias": ibias,
            "target_transimpedance_ohm": z_target,
        }
        return state, SizingReport(
            True,
            [
                "Transimpedance front-end sized from target Zt and bandwidth.",
                f"Feedback R ≈ {z_target:.3e} ohm, C ≈ {c_feedback:.3e} F.",
            ],
        )

    def _size_current_sense_amp_helper(self, state, constraints):
        sense_constraints = dict(constraints)
        sense_constraints.setdefault("R_load_ohm", float(constraints.get("R_load_ohm", 6000.0)))
        sense_constraints.setdefault("target_vov_v", float(constraints.get("target_vov_v", 0.18)))
        state, report = self._size_diff_pair(state, sense_constraints)
        report.notes.append("Current-sense helper uses differential front-end sizing baseline.")
        return state, report

    def _size_common_source_active_load(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        gain_db = float(constraints.get("target_gain_db", 12.0))
        Vov_n = float(constraints.get("target_vov_v", 0.18))
        Vov_p = float(constraints.get("target_vov_p_v", 0.22))
        # Match the LEVEL=1 model parameters used in the template netlist.
        mu_n = float(constraints.get("mu_cox_active_n_a_per_v2", 200e-6))
        mu_p = float(constraints.get("mu_cox_active_p_a_per_v2", 80e-6))
        L = float(constraints.get("L_active_m", 180e-9))
        gain_lin = 10 ** (gain_db / 20.0)
        id_bias = max(20e-6, min(300e-6, gain_lin * Vov_n / 2000.0))
        w_n = max(0.5, 2.0 * id_bias / (mu_n * Vov_n**2)) * L
        w_p = max(0.5, 1.2 * id_bias / (mu_p * Vov_p**2)) * L
        state["sizing"] = {
            "W_n": w_n,
            "L_n": L,
            "W_p": w_p,
            "L_p": L,
            "I_bias": id_bias,
            "Vin_bias": 0.5 + Vov_n,
            "target_vout_q": 0.9,
        }
        state["sizing"]["Vov_target"] = Vov_n
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_bias")
        return state, SizingReport(True, ["Common-source with PMOS active load sized from current target"])

    def _size_diode_connected_stage(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        gain_db = float(constraints.get("target_gain_db", 8.0))
        Vov_n = float(constraints.get("target_vov_v", 0.15))
        Vov_p = float(constraints.get("target_vov_p_v", 0.20))
        mu_n = float(constraints.get("mu_cox_active_n_a_per_v2", 200e-6))
        mu_p = float(constraints.get("mu_cox_active_p_a_per_v2", 80e-6))
        L = float(constraints.get("L_active_m", 180e-9))
        gain_lin = max(10 ** (gain_db / 20.0), 1.0)
        id_bias = max(35e-6, min(200e-6, gain_lin * Vov_n / 1500.0))
        w_n = max(0.5, 2.2 * id_bias / (mu_n * Vov_n**2)) * L
        w_p = max(0.3, 0.6 * id_bias / (mu_p * Vov_p**2)) * L
        state["sizing"] = {
            "W_n": w_n,
            "L_n": L,
            "W_p": w_p,
            "L_p": L,
            "I_bias": id_bias,
            "Vin_bias": min(vdd - 0.1, 0.55 + Vov_n),
            "target_vout_q": 0.9,
        }
        state["sizing"]["Vov_target"] = Vov_n
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_bias")
        report = SizingReport(True, ["Diode-connected MOS amplifier sized with weaker PMOS load to target moderate gain."])
        return state, report

    def _size_cascode_amplifier(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        gain_db = float(constraints.get("target_gain_db", 15.0))
        Vov = float(constraints.get("target_vov_v", 0.16))
        mu = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L = float(constraints.get("L_m", 180e-9))
        gain_lin = 10 ** (gain_db / 20.0)
        id_bias = max(30e-6, gain_lin * Vov / 10000.0)
        w = max(0.5, 2.0 * id_bias / (mu * Vov**2)) * L
        rd = max(1000.0, 0.35 * vdd / id_bias)
        state["sizing"] = {
            "W_in": w,
            "L_in": L,
            "W_cas": 1.2 * w,
            "L_cas": L,
            "R_D": rd,
            "I_bias": id_bias,
            "Vbias_cas": 0.9,
            "Vov_target": Vov,
        }
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_bias")
        return state, SizingReport(True, ["Cascode amplifier first-pass sizing complete"])

    def _size_nand2_cmos(self, state, constraints):
        L = float(constraints.get("L_m", 180e-9))
        wn = float(constraints.get("W_n_m", 1.2e-6))
        wp = float(constraints.get("W_p_m", 2.4e-6))
        load_cap = float(constraints.get("load_cap_f", 10e-15))
        state["sizing"] = {
            "W_n": wn,
            "L_n": L,
            "W_p": wp,
            "L_p": L,
            "C_load": load_cap,
        }
        return state, SizingReport(True, ["CMOS NAND2 transistor sizes assigned"])

    def _size_sram6t_cell(self, state, constraints):
        L = float(constraints.get("L_m", 180e-9))
        state["sizing"] = {
            "W_pullup": float(constraints.get("W_pullup_m", 0.8e-6)),
            "L_pullup": L,
            "W_pulldown": float(constraints.get("W_pulldown_m", 1.4e-6)),
            "L_pulldown": L,
            "W_access": float(constraints.get("W_access_m", 1.0e-6)),
            "L_access": L,
            "C_storage": float(constraints.get("storage_cap_f", 2e-15)),
        }
        return state, SizingReport(True, ["6T SRAM cell device sizes assigned"])

    def _size_lc_oscillator(self, state, constraints):
        L_tank = float(constraints.get("L_tank_h", 10e-9))
        target_f = float(constraints.get("target_osc_hz", 1e9))
        C_tank = 1.0 / ((2.0 * math.pi * target_f) ** 2 * L_tank)
        L = float(constraints.get("L_m", 180e-9))
        I_tail = float(constraints.get("tail_current_a", 100e-6))
        Vov = float(constraints.get("target_vov_v", 0.18))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        startup_margin = float(constraints.get("startup_margin_factor", 12.0))
        W_over_L = max(0.5, 2.0 * (I_tail / 2.0) / max(muCox * Vov**2, 1e-30))
        state["sizing"] = {
            "W_pair": float(constraints.get("W_pair_m", startup_margin * W_over_L * L)),
            "L_pair": L,
            "L_tank": L_tank,
            "C_tank": C_tank,
            "I_tail": I_tail,
            "R_tank_loss": float(constraints.get("r_tank_loss_ohm", 10000.0)),
            "Vov_target": Vov,
        }
        self._annotate_mos_sizing(state["sizing"], constraints, current_key="I_tail", ro_current_factor=0.5)
        return state, SizingReport(True, ["Cross-coupled LC oscillator tank values computed"])

    def _size_bandgap_reference(self, state, constraints):
        area_ratio = float(constraints.get("area_ratio", 8.0))
        target_vref = float(constraints.get("target_vref_v", 1.2))
        vt = 0.02585
        dvbe = vt * math.log(max(area_ratio, 1.0001))
        vbe_nom = float(constraints.get("vbe_nom_v", 0.7))
        ratio = max(2.0, (target_vref - vbe_nom) / max(dvbe, 1e-6))
        r1 = float(constraints.get("R1_ohm", 5000.0))
        r2 = ratio * r1
        state["sizing"] = {
            "I_core": float(constraints.get("i_core_a", 20e-6)),
            "area_ratio": area_ratio,
            "R1_ohm": r1,
            "R2_ohm": r2,
        }
        return state, SizingReport(True, ["Bandgap reference sized from target Vref and area ratio"])

    def _size_comparator(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        overdrive = float(constraints.get("input_overdrive_v", 10e-3))
        regen_tau = float(constraints.get("target_decision_tau_s", 1e-9))
        load_cap = float(constraints.get("load_cap_f", 50e-15))
        gm_lat = max(load_cap / max(regen_tau, 1e-15), 0.5e-3)
        state["sizing"] = {
            "gm_latch_s": gm_lat,
            "input_overdrive_v": overdrive,
            "vcm_v": float(constraints.get("vicm_v", 0.5 * vdd)),
            "load_cap_f": load_cap,
            "tail_current_a": max(50e-6, gm_lat * 0.1),
        }
        return state, SizingReport(
            True,
            [
                "Comparator proxy sized from input overdrive, decision time target, and load capacitance.",
                f"Estimated regenerative gm ≈ {gm_lat:.3e} S.",
            ],
        )
    
