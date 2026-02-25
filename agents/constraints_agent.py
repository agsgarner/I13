from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from core.shared_memory import SharedMemory
from agents.base_agent import BaseAgent

@dataclass
class ConstraintReport:
    passed: bool
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checked_topology: str = "unknown"
    completeness_score: float = 0.0
    required_constraints: List[str] = field(default_factory=list)
    required_sizing: List[str] = field(default_factory=list)


class ConstraintAgent(BaseAgent):

    REQUIRED_CONSTRAINT_KEYS = {
        "rc_lowpass": ["target_fc_hz"],
        "common_source_res_load": ["supply_v", "target_gain_db", "target_bw_hz", "power_limit_mw"],
        "diff_pair": ["supply_v", "target_gain_db", "target_bw_hz", "cm_input_v", "power_limit_mw"],
        "current_mirror": ["supply_v", "target_iout_a", "compliance_v", "accuracy_pct"],
    }

    REQUIRED_SIZING_KEYS = {
        "rc_lowpass": ["R_ohm", "C_f"],
        "common_source_res_load": ["W_m", "L_m", "R_D", "I_bias"],
        "diff_pair": ["W_in", "L_in", "W_tail", "L_tail", "I_tail", "R_load"],
        "current_mirror": ["W_ref", "L_ref", "W_out", "L_out", "I_ref"],
    }

    POSITIVE_CONSTRAINTS = {
        "rc_lowpass": ["target_fc_hz"],
        "common_source_res_load": ["supply_v", "target_bw_hz", "power_limit_mw"],
        "diff_pair": ["supply_v", "target_bw_hz", "power_limit_mw"],
        "current_mirror": ["supply_v", "target_iout_a", "compliance_v", "accuracy_pct"],
    }

    def run(self, memory: SharedMemory) -> Tuple[Dict[str, Any], ConstraintReport]:
        issues: List[str] = []
        warnings: List[str] = []

        state = memory.get_full_state()
        constraints = state.get("constraints")
        topology = state.get("selected_topology")
        sizing = state.get("sizing")

        if constraints is None:
            issues.append("Missing constraints")
        if topology is None:
            issues.append("Missing selected_topology")
        if sizing is None:
            issues.append("Missing sizing")

        if issues:
            report = ConstraintReport(False, issues, warnings, "unknown", 0.0)
            state["constraint_report"] = report.__dict__
            state["status"] = "constraints_failed"
            return state, report

        circuit_type = constraints.get("circuit_type", topology)

        required_constraints = self.REQUIRED_CONSTRAINT_KEYS.get(circuit_type, [])
        required_sizing = self.REQUIRED_SIZING_KEYS.get(circuit_type, [])

        for key in required_constraints:
            if constraints.get(key) is None:
                issues.append(f"Missing required constraint '{key}'")

        for key in required_sizing:
            if sizing.get(key) is None:
                issues.append(f"Missing required sizing parameter '{key}'")

        for key in self.POSITIVE_CONSTRAINTS.get(circuit_type, []):
            value = constraints.get(key)
            if value is not None and value <= 0:
                issues.append(f"Constraint '{key}' must be > 0")

        if circuit_type == "rc_lowpass":
            fc = constraints.get("target_fc_hz")
            R = sizing.get("R_ohm")
            C = sizing.get("C_f")
            if fc and R and C:
                fc_est = 1.0 / (2.0 * 3.141592653589793 * R * C)
                rel_err = abs(fc_est - fc) / fc
                if rel_err > 0.5:
                    warnings.append("Estimated cutoff differs significantly from target")

        if circuit_type == "common_source_res_load":
            vdd = constraints.get("supply_v")
            I = sizing.get("I_bias")
            pmax = constraints.get("power_limit_mw")
            if vdd and I and pmax:
                p_est = 1e3 * vdd * I
                if p_est > pmax:
                    issues.append("Estimated power exceeds power limit")

            gain = constraints.get("target_gain_db")
            if gain and gain > 40:
                warnings.append("High gain target may be unrealistic for single-stage CS")

        if circuit_type == "diff_pair":
            I_tail = sizing.get("I_tail")
            if I_tail is not None and I_tail <= 0:
                issues.append("Tail current must be positive")

        if circuit_type == "current_mirror":
            acc = constraints.get("accuracy_pct")
            if acc is not None and acc <= 0:
                issues.append("Accuracy percentage must be positive")

        present = sum(1 for k in required_constraints if constraints.get(k) is not None)
        completeness = present / len(required_constraints) if required_constraints else 1.0

        passed = len(issues) == 0

        report = ConstraintReport(
            passed=passed,
            issues=issues,
            warnings=warnings,
            checked_topology=circuit_type,
            completeness_score=completeness,
            required_constraints=required_constraints,
            required_sizing=required_sizing,
        )

        memory.write("constraints_report", report.__dict__)
        memory.write("status", "constraints_ok" if passed else "constraints_failed")

        return state, report