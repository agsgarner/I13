# I13/agents/constraints_agent.py

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
        "amplifier_differential": ["supply_v", "power_limit_mw"],
        "amplifier_differential_bjt": ["tail_current_a", "collector_res_ohm"],
        "opamp_two_stage": [
            "supply_v", "target_gain_db", "target_ugbw_hz",
            "phase_margin_deg", "load_cap_f", "power_limit_mw"
        ],
        "bias_current_mirror": ["supply_v", "target_iout_a", "compliance_v"],
        "transconductor": ["target_gm_s"],
        "comparator": ["supply_v"]
    }

    REQUIRED_SIZING_KEYS_BY_TOPOLOGY = {
        "rc_lowpass": ["R_ohm", "C_f"],
        "common_source_res_load": ["W_m", "L_m", "R_D", "I_bias"],
        "diff_pair": ["W_in", "L_in", "W_tail", "L_tail", "I_tail", "R_load"],
        "bjt_diff_pair": ["I_tail", "Ic_each", "R_C", "gm_each"],
        "current_mirror": ["W_ref", "L_ref", "W_out", "L_out", "I_ref"],
        "two_stage_miller": ["Cc_f", "gm1_target_s", "I_stage1_a", "I_stage2_a"],
        "gm_stage": ["gm_target_s", "I_bias_a", "W_m", "L_m"]
    }

    POSITIVE_CONSTRAINTS_BY_TEMPLATE = {
        "filter_rc": ["target_fc_hz"],
        "amplifier_single_stage": ["supply_v", "target_bw_hz", "power_limit_mw"],
        "amplifier_differential": ["supply_v", "power_limit_mw"],
        "amplifier_differential_bjt": ["tail_current_a", "collector_res_ohm"],
        "opamp_two_stage": ["supply_v", "target_ugbw_hz", "power_limit_mw"],
        "bias_current_mirror": ["supply_v", "target_iout_a", "compliance_v"],
        "transconductor": ["target_gm_s"],
        "comparator": ["supply_v"]
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
            VDD = constraints.get("supply_v")
            I = sizing.get("I_bias")
            RD = sizing.get("R_D")
            Vov = sizing.get("Vov_target", constraints.get("target_vov_v", 0.2))

            if VDD and I and RD:
                vdrop = I * RD
                vout_est = VDD - vdrop

                if vdrop > 0.8 * VDD:
                    warnings.append(
                        f"Drain resistor drop consumes most of VDD; "
                        f"vdrop={vdrop:.3f} V, VDD={VDD:.3f} V."
                    )

                if vout_est < Vov:
                    issues.append(
                        f"Estimated Vout too low to keep transistor in saturation: "
                        f"Vout_est={vout_est:.3f} V, Vov={Vov:.3f} V."
                    )

        elif topology_key == "diff_pair":
            I_tail = sizing.get("I_tail")
            R_load = sizing.get("R_load")
            if I_tail and R_load:
                vdrop = (I_tail / 2.0) * R_load
                supply_v = constraints.get("supply_v")
                if supply_v and vdrop > 0.5 * supply_v:
                    warnings.append("Load resistor drop may limit differential output swing.")

            vid_max = constraints.get("max_input_diff_v")
            if vid_max is not None and vid_max > 0.2:
                warnings.append("Large differential input may push pair out of small-signal region.")

        elif topology_key == "bjt_diff_pair":
            gm = sizing.get("gm_each")
            if gm is not None and gm < 1e-4:
                warnings.append("BJT differential pair gm is low; gain may be limited.")

        elif topology_key == "current_mirror":
            compliance_v = constraints.get("compliance_v")
            vov = sizing.get("Vov_target", 0.2)
            if compliance_v is not None and compliance_v < vov:
                issues.append("Compliance voltage too low for desired mirror overdrive.")

            ratio = sizing.get("mirror_ratio", 1.0)
            if ratio > 20:
                warnings.append("Large mirror ratio may be sensitive to mismatch.")

        elif topology_key == "two_stage_miller":
            cc = sizing.get("Cc_f")
            cl = constraints.get("load_cap_f")
            pm = constraints.get("phase_margin_deg")
            if cc and cl and cc < 0.1 * cl:
                warnings.append("Compensation capacitor may be too small relative to load capacitance.")
            if pm is not None and pm < 50:
                warnings.append("Requested phase margin is low for a stable design.")

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
