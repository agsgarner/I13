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
        max_step_up: float = 1.5,
        max_step_down: float = 0.7,
        min_factor: float = 0.2,
        max_factor: float = 5.0,
        max_retries: int = 1,
        wait: float = 0,
    ):
        super().__init__(llm=llm, max_retries=max_retries, wait=wait)
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

        if not topo:
            report = RefinementReport(False, {}, ["No topology found"], "stop")
            memory.write("refinement_report", report.__dict__)
            memory.write("status", DesignStatus.REFINEMENT_SKIPPED)
            return state, report

        if topo == "rc_lowpass":
            state, report = self._refine_rc_lowpass(state, constraints, sizing, sim)
        elif topo == "common_source_res_load":
            state, report = self._refine_common_source(state, constraints, sizing, sim)
        elif topo == "current_mirror":
            state, report = self._refine_current_mirror(state, constraints, sizing, sim)
        else:
            report = RefinementReport(
                changed=False,
                changes={},
                notes=[f"Refinement not implemented for topology '{topo}' yet"],
                next_action="stop",
            )
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_SKIPPED

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

        W = sizing.get("W_m")
        I = sizing.get("I_bias")
        RD = sizing.get("R_D")

        if W is None or I is None or RD is None:
            report = RefinementReport(False, {}, ["Missing sizing keys (W_m, I_bias, R_D)"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_FAILED
            return state, report

        W = float(W)
        I = float(I)
        RD = float(RD)

        changes: Dict[str, Any] = {}
        notes: List[str] = []

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
                step = self._clamp_step(1.0 + min(0.5, gain_err_db / 20.0))
                new_W = W * step
                apply_change(
                    "W_m",
                    W,
                    new_W,
                    f"Gain low: {gain_db:.2f} dB vs target {target_gain_db:.2f} dB. Increased W_m.",
                )
                W = new_W

                new_RD = RD * 1.2
                apply_change(
                    "R_D",
                    RD,
                    new_RD,
                    f"Gain low: {gain_db:.2f} dB vs target {target_gain_db:.2f} dB. Increased R_D.",
                )
                RD = new_RD

            elif gain_err_db < -1.0:
                step = self._clamp_step(1.0 - min(0.3, (-gain_err_db) / 30.0))
                new_W = max(1e-9, W * step)
                apply_change(
                    "W_m",
                    W,
                    new_W,
                    f"Gain high: {gain_db:.2f} dB vs target {target_gain_db:.2f} dB. Decreased W_m.",
                )
                W = new_W

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

    def _refine_current_mirror(
        self,
        state: Dict[str, Any],
        constraints: Dict[str, Any],
        sizing: Dict[str, Any],
        sim: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], RefinementReport]:
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

        W_out = float(sizing.get("W_out", 0.0))
        if W_out <= 0:
            report = RefinementReport(False, {}, ["Missing or invalid W_out"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = DesignStatus.REFINEMENT_FAILED
            return state, report

        factor = self._clamp_abs(target_i / sim_i)
        step = self._clamp_step(factor)
        new_W_out = max(1e-12, W_out * step)

        state["sizing"]["W_out"] = new_W_out
        report = RefinementReport(
            changed=True,
            changes={"W_out": {"old": W_out, "new": new_W_out, "factor": step}},
            notes=[f"Adjusted mirror output width to move iout from {sim_i:.3e} A toward {target_i:.3e} A."],
            next_action="rerun_constraints_and_spice",
        )
        state["refinement_report"] = report.__dict__
        state["status"] = DesignStatus.REFINED
        return state, report
