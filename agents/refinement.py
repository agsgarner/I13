from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class RefinementReport:
    changed: bool
    changes: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    next_action: str = "rerun_spice"


class RefinementAgent:
    def __init__(
        self,
        max_step_up: float = 1.5,
        max_step_down: float = 0.7,
        min_factor: float = 0.2,
        max_factor: float = 5.0,
    ):
        self.max_step_up = max_step_up
        self.max_step_down = max_step_down
        self.min_factor = min_factor
        self.max_factor = max_factor

    def run(self, state: Dict[str, Any]) -> Tuple[Dict[str, Any], RefinementReport]:
        constraints = state.get("constraints") or {}
        topo = state.get("selected_topology") or constraints.get("circuit_type")
        sizing = state.get("sizing") or {}
        sim = (state.get("sim") or {}).get("metrics") or state.get("sim_metrics") or {}

        changes: Dict[str, Any] = {}
        notes: List[str] = []

        if not topo:
            report = RefinementReport(False, {}, ["No topology found"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = "refinement_skipped"
            return state, report

        if topo == "rc_lowpass":
            state, report = self._refine_rc_lowpass(state, constraints, sizing, sim)
            return state, report

        if topo == "common_source_res_load":
            state, report = self._refine_common_source(state, constraints, sizing, sim)
            return state, report

        report = RefinementReport(
            changed=False,
            changes={},
            notes=[f"Refinement not implemented for topology '{topo}' yet"],
            next_action="stop",
        )
        state["refinement_report"] = report.__dict__
        state["status"] = "refinement_skipped"
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
        fc_sim = sim.get("fc_hz")

        if target_fc is None:
            report = RefinementReport(False, {}, ["Missing target_fc_hz"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = "refinement_failed"
            return state, report

        if fc_sim is None:
            report = RefinementReport(False, {}, ["Missing sim fc_hz (run SPICE first)"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = "refinement_failed"
            return state, report

        R = float(sizing.get("R_ohm", 0.0))
        C = float(sizing.get("C_f", 0.0))
        if R <= 0 or C <= 0:
            report = RefinementReport(False, {}, ["Invalid R_ohm or C_f in sizing"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = "refinement_failed"
            return state, report

        ratio = fc_sim / target_fc
        if ratio <= 0:
            report = RefinementReport(False, {}, ["Bad fc ratio"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = "refinement_failed"
            return state, report

        # Want fc_sim -> target_fc.
        # fc ∝ 1/(RC). If fc_sim is too high, increase R or C. If too low, decrease R or C.
        desired_RC_scale = ratio  # because fc_new = fc_old / scale; need scale = fc_old/target = ratio
        desired_RC_scale = self._clamp_abs(desired_RC_scale)
        step = self._clamp_step(desired_RC_scale)

        new_R = R * step

        state["sizing"]["R_ohm"] = new_R
        report = RefinementReport(
            changed=True,
            changes={"R_ohm": {"old": R, "new": new_R, "factor": step}},
            notes=[
                f"Adjusted R to move fc toward target. fc_sim={fc_sim:.3g} Hz, target={target_fc:.3g} Hz."
            ],
            next_action="rerun_spice",
        )
        state["refinement_report"] = report.__dict__
        state["status"] = "refined"
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
        vdd = constraints.get("supply_v")

        gain_db = sim.get("gain_db")
        bw_hz = sim.get("bandwidth_hz")
        power_mw = sim.get("power_mw")

        W = sizing.get("W_m")
        I = sizing.get("I_bias")
        RD = sizing.get("R_D")

        if W is None or I is None or RD is None:
            report = RefinementReport(False, {}, ["Missing sizing keys (W_m, I_bias, R_D)"], "stop")
            state["refinement_report"] = report.__dict__
            state["status"] = "refinement_failed"
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

        # 1) Enforce power limit (hard-ish): if power is too high, reduce bias current first.
        if power_limit_mw is not None and power_mw is not None:
            if power_mw > power_limit_mw:
                # reduce current by ratio, but clamp the step
                factor = power_limit_mw / power_mw
                factor = self._clamp_abs(factor)
                step = self._clamp_step(factor)
                new_I = max(1e-12, I * step)
                apply_change(
                    "I_bias",
                    I,
                    new_I,
                    f"Power too high: {power_mw:.3g} mW > {power_limit_mw:.3g} mW. Reduced I_bias.",
                )
                I = new_I

        # 2) Fix gain: for CS with resistive load, gain ~ gm*RD. Increasing W or I increases gm (roughly).
        if target_gain_db is not None and gain_db is not None:
            gain_err_db = target_gain_db - gain_db

            if gain_err_db > 1.0:
                # Need more gain -> increase W_m a bit (safer than RD because RD can hurt headroom)
                step = self._clamp_step(1.0 + min(0.5, gain_err_db / 20.0))
                new_W = W * step
                apply_change(
                    "W_m",
                    W,
                    new_W,
                    f"Gain low: {gain_db:.2f} dB vs target {target_gain_db:.2f} dB. Increased W_m.",
                )
                W = new_W

            elif gain_err_db < -1.0:
                # Gain too high -> decrease W_m slightly (or RD). We'll decrease W.
                step = self._clamp_step(1.0 - min(0.3, (-gain_err_db) / 30.0))
                new_W = max(1e-9, W * step)
                apply_change(
                    "W_m",
                    W,
                    new_W,
                    f"Gain high: {gain_db:.2f} dB vs target {target_gain_db:.2f} dB. Decreased W_m.",
                )
                W = new_W

        # 3) Fix bandwidth: if BW too low, reduce RD (lowers gain though) or reduce W (lowers cap).
        # Baseline heuristic: if BW below target by a lot, reduce RD a bit.
        if target_bw_hz is not None and bw_hz is not None:
            bw_ratio = bw_hz / target_bw_hz if target_bw_hz > 0 else 1.0
            if bw_ratio < 0.8:
                step = self._clamp_step(0.85)  # reduce RD
                new_RD = max(1e-3, RD * step)
                apply_change(
                    "R_D",
                    RD,
                    new_RD,
                    f"Bandwidth low: {bw_hz:.3g} Hz vs target {target_bw_hz:.3g} Hz. Reduced R_D to improve BW.",
                )
                RD = new_RD

        changed = len(changes) > 0
        next_action = "rerun_spice" if changed else "stop"

        if not changed:
            notes.append("No refinements applied (already close to targets or missing sim metrics).")

        report = RefinementReport(changed=changed, changes=changes, notes=notes, next_action=next_action)
        state["refinement_report"] = report.__dict__
        state["status"] = "refined" if changed else "refinement_no_change"
        return state, report


if __name__ == "__main__":
    # quick sanity demo for RC
    st = {
        "constraints": {"circuit_type": "rc_lowpass", "target_fc_hz": 1000.0},
        "selected_topology": "rc_lowpass",
        "sizing": {"R_ohm": 10000.0, "C_f": 10e-9},
        "sim": {"metrics": {"fc_hz": 2000.0}},
    }
    agent = RefinementAgent()
    st, rep = agent.run(st)
    print(rep.changed)
    print(rep.changes)
    print(rep.notes)
