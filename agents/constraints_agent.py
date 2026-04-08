# I13/agents/constraints_agent.py

from dataclasses import dataclass, field
from typing import List

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
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
    ANALYSIS_TARGET_KEYS = {
        "ac": {
            "target_fc_hz",
            "target_gain_db",
            "target_bw_hz",
            "target_ugbw_hz",
            "phase_margin_deg",
            "target_center_hz",
            "target_stopband_atten_db",
        },
        "dc": {"target_iout_a", "compliance_v", "target_vref_v"},
        "tran": {"target_slew_v_per_us", "target_osc_hz"},
        "op": {"power_limit_mw", "supply_v", "target_gm_s"},
    }
    SIMULATION_TARGET_KEYS = set().union(*ANALYSIS_TARGET_KEYS.values())

    REQUIRED_CONSTRAINT_KEYS_BY_TEMPLATE = {
        "filter_rc": ["target_fc_hz"],
        "filter_rlc_lowpass": ["target_fc_hz"],
        "filter_rlc_highpass": ["target_fc_hz"],
        "filter_rlc_bandpass": ["target_center_hz", "target_bw_hz"],
        "amplifier_single_stage": ["supply_v", "target_gain_db", "target_bw_hz", "power_limit_mw"],
        "amplifier_differential": ["supply_v", "power_limit_mw"],
        "amplifier_differential_bjt": ["tail_current_a", "collector_res_ohm"],
        "opamp_two_stage": [
            "supply_v", "target_gain_db", "target_ugbw_hz",
            "phase_margin_deg", "load_cap_f", "power_limit_mw"
        ],
        "bias_current_mirror": ["supply_v", "target_iout_a", "compliance_v"],
        "transconductor": ["target_gm_s"],
        "source_follower": ["supply_v"],
        "common_gate_amp": ["supply_v"],
        "amplifier_source_degenerated": ["supply_v", "target_gain_db", "target_bw_hz", "power_limit_mw"],
        "amplifier_active_load": ["supply_v", "target_gain_db", "power_limit_mw"],
        "amplifier_cascode": ["supply_v", "target_gain_db", "power_limit_mw"],
        "digital_cmos_gate": ["supply_v"],
        "memory_sram_cell": ["supply_v"],
        "oscillator_lc": ["supply_v"],
        "reference_bandgap": ["supply_v"],
        "comparator": ["supply_v"]
    }

    REQUIRED_SIZING_KEYS_BY_TOPOLOGY = {
        "rc_lowpass": ["R_ohm", "C_f"],
        "rlc_lowpass_2nd_order": ["R_ohm", "L_h", "C_f", "q_target", "damping_ratio"],
        "rlc_highpass_2nd_order": ["R_ohm", "L_h", "C_f", "q_target", "damping_ratio"],
        "rlc_bandpass_2nd_order": ["R_ohm", "L_h", "C_f", "q_target"],
        "common_source_res_load": ["W_m", "L_m", "R_D", "I_bias"],
        "diff_pair": ["W_in", "L_in", "W_tail", "L_tail", "I_tail", "R_load"],
        "bjt_diff_pair": ["I_tail", "Ic_each", "R_C", "gm_each"],
        "current_mirror": ["W_ref", "L_ref", "W_out", "L_out", "I_ref"],
        "two_stage_miller": ["Cc_f", "gm1_target_s", "I_stage1_a", "I_stage2_a"],
        "gm_stage": ["gm_target_s", "I_bias_a", "W_m", "L_m"],
        "common_drain": ["W_m", "L_m", "I_bias", "R_source", "Vbias"],
        "common_gate": ["W_m", "L_m", "I_bias", "R_D", "Vbias"],
        "source_degenerated_cs": ["W_m", "L_m", "R_D", "I_bias", "R_S"],
        "common_source_active_load": ["W_n", "L_n", "W_p", "L_p", "I_bias"],
        "diode_connected_stage": ["W_n", "L_n", "W_p", "L_p", "I_bias"],
        "cascode_amplifier": ["W_in", "L_in", "W_cas", "L_cas", "R_D", "I_bias", "Vbias_cas"],
        "nand2_cmos": ["W_n", "L_n", "W_p", "L_p", "C_load"],
        "sram6t_cell": ["W_pullup", "L_pullup", "W_pulldown", "L_pulldown", "W_access", "L_access"],
        "lc_oscillator_cross_coupled": ["W_pair", "L_pair", "L_tank", "C_tank", "I_tail"],
        "bandgap_reference_core": ["I_core", "area_ratio", "R1_ohm", "R2_ohm"],
    }

    POSITIVE_CONSTRAINTS_BY_TEMPLATE = {
        "filter_rc": ["target_fc_hz"],
        "filter_rlc_lowpass": ["target_fc_hz"],
        "filter_rlc_highpass": ["target_fc_hz"],
        "filter_rlc_bandpass": ["target_center_hz", "target_bw_hz"],
        "amplifier_single_stage": ["supply_v", "target_bw_hz", "power_limit_mw"],
        "amplifier_differential": ["supply_v", "power_limit_mw"],
        "amplifier_differential_bjt": ["tail_current_a", "collector_res_ohm"],
        "opamp_two_stage": ["supply_v", "target_ugbw_hz", "power_limit_mw"],
        "bias_current_mirror": ["supply_v", "target_iout_a", "compliance_v"],
        "transconductor": ["target_gm_s"],
        "source_follower": ["supply_v"],
        "common_gate_amp": ["supply_v"],
        "amplifier_source_degenerated": ["supply_v", "target_bw_hz", "power_limit_mw"],
        "amplifier_active_load": ["supply_v", "power_limit_mw"],
        "amplifier_cascode": ["supply_v", "power_limit_mw"],
        "digital_cmos_gate": ["supply_v"],
        "memory_sram_cell": ["supply_v"],
        "oscillator_lc": ["supply_v"],
        "reference_bandgap": ["supply_v"],
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
            memory.write("status", DesignStatus.CONSTRAINTS_FAILED)
            return state, report

        topology_meta = TOPOLOGY_LIBRARY.get(topology_key)
        if topology_meta is None:
            report = ConstraintReport(False, issues=[f"Unknown topology '{topology_key}'"])
            memory.write("constraints_report", report.__dict__)
            memory.write("status", DesignStatus.CONSTRAINTS_FAILED)
            return state, report

        template = topology_meta["constraint_template"]
        simulation_plan = (
            (state.get("case_metadata") or {}).get("simulation_plan")
            or topology_meta.get("simulation_plan")
            or {}
        )
        required_constraints = self.REQUIRED_CONSTRAINT_KEYS_BY_TEMPLATE.get(template, [])
        required_sizing = self.REQUIRED_SIZING_KEYS_BY_TOPOLOGY.get(topology_key, [])
        case_meta = state.get("case_metadata") or {}
        if topology_key == "two_stage_miller" and case_meta.get("demo_model") == "behavioral_opamp_proxy":
            required_sizing = ["I_tail", "W_in", "W_cas_n", "W_load_p", "Vbias_n", "Vbias_p"]

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

        required_targets = simulation_plan.get("required_constraint_targets") or []
        for key in required_targets:
            if constraints.get(key) is None:
                issues.append(
                    f"Simulation plan for '{topology_key}' requires constraint target '{key}'"
                )

        analyses = simulation_plan.get("analyses") or []
        relevant_keys = set()
        for analysis in analyses:
            relevant_keys.update(self.ANALYSIS_TARGET_KEYS.get(analysis, set()))
        irrelevant_targets = []
        for key in constraints.keys():
            if key not in self.SIMULATION_TARGET_KEYS:
                continue
            if key in required_constraints or key in required_targets:
                continue
            if relevant_keys and key not in relevant_keys:
                irrelevant_targets.append(key)
        if irrelevant_targets:
            warnings.append(
                "Constraint targets not exercised by the planned analyses: "
                + ", ".join(sorted(irrelevant_targets))
            )

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

        elif topology_key in {"rlc_lowpass_2nd_order", "rlc_highpass_2nd_order"}:
            l_h = sizing.get("L_h")
            c_f = sizing.get("C_f")
            q_target = sizing.get("q_target")
            if l_h is not None and l_h <= 0:
                issues.append("L_h must be > 0")
            if c_f is not None and c_f <= 0:
                issues.append("C_f must be > 0")
            if q_target is not None and q_target <= 0:
                issues.append("q_target must be > 0")
            if sizing.get("filter_order") not in (2, None):
                warnings.append("Current implementation realizes a single second-order section even if filter_order > 2.")
            if constraints.get("target_stopband_atten_db") is not None and constraints.get("target_stopband_atten_db") > 40:
                warnings.append("Single-section RLC filters may not meet aggressive stopband attenuation without cascading sections.")

        elif topology_key == "rlc_bandpass_2nd_order":
            center_hz = constraints.get("target_center_hz")
            bw_hz = constraints.get("target_bw_hz")
            if center_hz is not None and bw_hz is not None and bw_hz >= center_hz:
                issues.append("target_bw_hz must be less than target_center_hz for a meaningful band-pass section.")
            q_target = sizing.get("q_target")
            if q_target is not None and q_target > 20:
                warnings.append("Very high-Q band-pass targets may be sensitive to component tolerance and loss.")

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

        elif topology_key == "bandgap_reference_core":
            ratio = sizing.get("R2_ohm", 0.0) / max(sizing.get("R1_ohm", 1.0), 1e-30)
            if ratio < 5 or ratio > 20:
                warnings.append("Bandgap resistor ratio is outside the usual first-pass range.")

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
        memory.write("status", DesignStatus.CONSTRAINTS_OK if passed else DesignStatus.CONSTRAINTS_FAILED)
        return state, report
