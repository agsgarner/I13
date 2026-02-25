# I13/agents/constraint_agent.py

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

        "filter_rc": ["target_fc_hz"],

        "amplifier_single_stage": [
            "supply_v",
            "target_gain_db",
            "target_bw_hz",
            "power_limit_mw"
        ],

        "amplifier_two_stage": [
            "supply_v",
            "target_gain_db",
            "target_ugbw_hz",
            "phase_margin_deg",
            "load_cap_f",
            "power_limit_mw"
        ],

        "opamp_two_stage": [
            "supply_v",
            "target_gain_db",
            "target_ugbw_hz",
            "phase_margin_deg",
            "cm_input_range",
            "load_cap_f",
            "power_limit_mw"
        ],

        "bias_current_mirror": [
            "supply_v",
            "target_iout_a",
            "accuracy_pct",
            "compliance_v"
        ]
    }

    REQUIRED_SIZING_KEYS = {

        "filter_rc": ["R_ohm", "C_f"],

        "amplifier_single_stage": [
            "W", "L", "I_bias"
        ],

        "amplifier_two_stage": [
            "W1", "L1", "W2", "L2", "I_bias", "Cc"
        ],

        "opamp_two_stage": [
            "W1", "L1", "W2", "L2", "I_bias", "Cc"
        ],

        "bias_current_mirror": [
            "W_ref", "L_ref", "W_out", "L_out", "I_ref"
        ]
    }

    POSITIVE_CONSTRAINTS = {
        "filter_rc": ["target_fc_hz"],
        "amplifier_single_stage": ["supply_v", "target_bw_hz", "power_limit_mw"],
        "amplifier_two_stage": ["supply_v", "target_ugbw_hz", "power_limit_mw"],
        "opamp_two_stage": ["supply_v", "target_ugbw_hz", "power_limit_mw"],
        "bias_current_mirror": ["supply_v", "target_iout_a", "compliance_v"]
    }

    def run(self, memory: SharedMemory) -> Tuple[Dict[str, Any], ConstraintReport]:

        issues: List[str] = []
        warnings: List[str] = []

        state = memory.get_full_state()
        constraints = state.get("constraints")
        topology_key = state.get("selected_topology")
        sizing = state.get("sizing")

        if constraints is None:
            issues.append("Missing constraints")
        if topology_key is None:
            issues.append("Missing selected topology")
        if sizing is None:
            issues.append("Missing sizing")

        if issues:
            report = ConstraintReport(False, issues, warnings)
            memory.write("constraints_report", report.__dict__)
            memory.write("status", "constraints_failed")
            return state, report

        template = topology_key
        required_constraints = self.REQUIRED_CONSTRAINT_KEYS.get(template, [])
        required_sizing = self.REQUIRED_SIZING_KEYS.get(template, [])

        for key in required_constraints:
            if constraints.get(key) is None:
                issues.append(f"Missing required constraint '{key}'")

        for key in required_sizing:
            if sizing.get(key) is None:
                issues.append(f"Missing required sizing parameter '{key}'")

        for key in self.POSITIVE_CONSTRAINTS.get(template, []):
            val = constraints.get(key)
            if val is not None and val <= 0:
                issues.append(f"Constraint '{key}' must be > 0")

        if template == "filter_rc":
            fc = constraints.get("target_fc_hz")
            R = sizing.get("R_ohm")
            C = sizing.get("C_f")
            if fc and R and C:
                fc_est = 1.0 / (2.0 * 3.141592653589793 * R * C)
                rel_err = abs(fc_est - fc) / fc
                if rel_err > 0.3:
                    warnings.append("Cutoff frequency mismatch >30%")

        if template == "amplifier_single_stage":
            gain = constraints.get("target_gain_db")
            if gain and gain > 45:
                warnings.append("High gain may require multi-stage topology")

        passed = len(issues) == 0
        completeness = (
            sum(1 for k in required_constraints if constraints.get(k) is not None)
            / len(required_constraints)
            if required_constraints else 1.0
        )

        report = ConstraintReport(
            passed=passed,
            issues=issues,
            warnings=warnings,
            checked_topology=topology_key,
            completeness_score=completeness,
            required_constraints=required_constraints,
            required_sizing=required_sizing,
        )

        memory.write("constraints_report", report.__dict__)
        memory.write("status", "constraints_ok" if passed else "constraints_failed")

        return state, report
    