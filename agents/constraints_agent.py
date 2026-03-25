# I13/agents/constraint_agent.py

from dataclasses import dataclass, field
from typing import List

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory
from core.topology_library import TOPOLOGY_LIBRARY


@dataclass
class ConstraintReport:
    passed: bool
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checked_topology: str = "unknown"
    required_constraints: List[str] = field(default_factory=list)
    required_sizing: List[str] = field(default_factory=list)
    constraint_template: str = "unknown"


class ConstraintAgent(BaseAgent):
    REQUIRED_CONSTRAINT_KEYS_BY_TEMPLATE = {
        "filter_rc": ["target_fc_hz"],
        "amplifier_single_stage": ["supply_v", "target_gain_db", "target_bw_hz", "power_limit_mw"],
        "opamp_two_stage": [
            "supply_v", "target_gain_db", "target_ugbw_hz",
            "phase_margin_deg", "load_cap_f", "power_limit_mw"
        ],
        "bias_current_mirror": ["supply_v", "target_iout_a", "accuracy_pct", "compliance_v"]
    }

    REQUIRED_SIZING_KEYS_BY_TOPOLOGY = {
        "rc_lowpass": ["R_ohm", "C_f"],
        "common_source_res_load": ["W_m", "L_m", "R_D", "I_bias"],
        "diff_pair": ["W_in", "L_in", "W_tail", "L_tail", "I_tail", "R_load"],
        "current_mirror": ["W_ref", "L_ref", "W_out", "L_out", "I_ref"]
    }

    POSITIVE_CONSTRAINTS_BY_TEMPLATE = {
        "filter_rc": ["target_fc_hz"],
        "amplifier_single_stage": ["supply_v", "target_bw_hz", "power_limit_mw"],
        "opamp_two_stage": ["supply_v", "target_ugbw_hz", "power_limit_mw"],
        "bias_current_mirror": ["supply_v", "target_iout_a", "compliance_v"]
    }

    def run_agent(self, memory: SharedMemory):
        state = memory.get_full_state()
        constraints = state.get("constraints") or {}
        topology_key = state.get("selected_topology")
        sizing = state.get("sizing") or {}

        issues = []
        warnings = []

        if not topology_key:
            issues.append("Missing selected topology")
        if not constraints:
            issues.append("Missing constraints")
        if not sizing:
            issues.append("Missing sizing")

        if issues:
            report = ConstraintReport(False, issues=issues, warnings=warnings)
            memory.write("constraints_report", report.__dict__)
            memory.write("status", "constraints_failed")
            return state, report

        topology_meta = TOPOLOGY_LIBRARY.get(topology_key)
        if topology_meta is None:
            report = ConstraintReport(False, issues=[f"Unknown topology '{topology_key}'"])
            memory.write("constraints_report", report.__dict__)
            memory.write("status", "constraints_failed")
            return state, report

        template = topology_meta["constraint_template"]
        required_constraints = self.REQUIRED_CONSTRAINT_KEYS_BY_TEMPLATE.get(template, [])
        required_sizing = self.REQUIRED_SIZING_KEYS_BY_TOPOLOGY.get(topology_key, [])

        for key in required_constraints:
            if constraints.get(key) is None:
                issues.append(f"Missing required constraint '{key}'")

        for key in required_sizing:
            if sizing.get(key) is None:
                issues.append(f"Missing required sizing parameter '{key}'")

        for key in self.POSITIVE_CONSTRAINTS_BY_TEMPLATE.get(template, []):
            val = constraints.get(key)
            if val is not None and val <= 0:
                issues.append(f"Constraint '{key}' must be > 0")

        # topology-specific sanity checks
        if topology_key == "rc_lowpass":
            R = sizing.get("R_ohm")
            C = sizing.get("C_f")
            fc_target = constraints.get("target_fc_hz")
            if R is not None and R <= 0:
                issues.append("R_ohm must be > 0")
            if C is not None and C <= 0:
                issues.append("C_f must be > 0")
            if R and C and fc_target:
                fc_est = 1.0 / (2.0 * 3.141592653589793 * R * C)
                rel_err = abs(fc_est - fc_target) / fc_target
                if rel_err > 0.30:
                    warnings.append("Initial RC sizing is more than 30% away from target_fc_hz")

        elif topology_key == "common_source_res_load":
            if sizing.get("W_m", 0) <= 0:
                issues.append("W_m must be > 0")
            if sizing.get("L_m", 0) <= 0:
                issues.append("L_m must be > 0")
            if sizing.get("R_D", 0) <= 0:
                issues.append("R_D must be > 0")
            if sizing.get("I_bias", 0) <= 0:
                issues.append("I_bias must be > 0")

            gain_db = constraints.get("target_gain_db")
            if gain_db is not None and gain_db > 45:
                warnings.append("Requested gain may be high for a single-stage common-source with resistive load")

        elif topology_key == "diff_pair":
            for key in ["W_in", "L_in", "W_tail", "L_tail", "I_tail", "R_load"]:
                if sizing.get(key, 0) <= 0:
                    issues.append(f"{key} must be > 0")

        elif topology_key == "current_mirror":
            for key in ["W_ref", "L_ref", "W_out", "L_out", "I_ref"]:
                if sizing.get(key, 0) <= 0:
                    issues.append(f"{key} must be > 0")

        passed = len(issues) == 0

        report = ConstraintReport(
            passed=passed,
            issues=issues,
            warnings=warnings,
            checked_topology=topology_key,
            required_constraints=required_constraints,
            required_sizing=required_sizing,
            constraint_template=template
        )

        memory.write("constraints_report", report.__dict__)
        memory.write("status", "constraints_ok" if passed else "constraints_failed")
        return state, report
    