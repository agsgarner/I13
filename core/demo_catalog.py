import re

from core.topology_library import TOPOLOGY_LIBRARY


def slugify_label(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return text.strip("-") or "unnamed"


def describe_case_for_artifacts(case: dict) -> str:
    case_key = case.get("case_key") or case.get("key") or "case"
    display_name = case.get("display_name") or case_key
    return f"{case_key}_{slugify_label(display_name)}"


def build_case_simulation_plan(case: dict) -> dict:
    topology_key = case.get("forced_topology")
    topology_meta = TOPOLOGY_LIBRARY.get(topology_key, {})
    base_plan = dict(topology_meta.get("simulation_plan") or {})
    if case.get("simulation_plan"):
        base_plan.update(case["simulation_plan"])
    if "analyses" in base_plan:
        base_plan["analyses"] = list(base_plan["analyses"])
    if "primary_metrics" in base_plan:
        base_plan["primary_metrics"] = list(base_plan["primary_metrics"])
    if "required_constraint_targets" in base_plan:
        base_plan["required_constraint_targets"] = list(base_plan["required_constraint_targets"])
    return base_plan


DEMO_CASES = {
    "rc": {
        "display_name": "Single-Stage RC Low-Pass Filter",
        "specification": "Design a first-order low-pass filter with approximately 1 kHz cutoff.",
        "forced_topology": "rc_lowpass",
        "constraints": {
            "target_fc_hz": 1000.0,
            "fixed_cap_f": 10e-9,
            "vin_ac": 1.0,
            "vin_step": 1.0,
        },
    },
    "butterworth_rlc_lowpass": {
        "display_name": "Butterworth 2-Pole RLC Low-Pass Filter",
        "specification": "Design a second-order Butterworth low-pass filter using an RLC section for a clean flat passband.",
        "forced_topology": "rlc_lowpass_2nd_order",
        "constraints": {
            "target_fc_hz": 5000.0,
            "response_family": "butterworth",
            "filter_order": 2,
            "source_res_ohm": 50.0,
            "load_res_ohm": 10000.0,
            "fixed_cap_f": 10e-9,
            "vin_ac": 1.0,
            "vin_step": 1.0,
            "target_stopband_atten_db": 30.0,
        },
    },
    "rlc_highpass": {
        "display_name": "Second-Order RLC High-Pass Filter",
        "specification": "Design a second-order RLC high-pass filter for AC-coupled signal conditioning.",
        "forced_topology": "rlc_highpass_2nd_order",
        "constraints": {
            "target_fc_hz": 2000.0,
            "response_family": "bessel",
            "filter_order": 2,
            "source_res_ohm": 50.0,
            "load_res_ohm": 5000.0,
            "fixed_cap_f": 4.7e-9,
            "vin_ac": 1.0,
            "vin_step": 1.0,
        },
    },
    "rlc_bandpass": {
        "display_name": "Second-Order RLC Band-Pass Filter",
        "specification": "Design a second-order RLC band-pass filter with a defined center frequency and bandwidth.",
        "forced_topology": "rlc_bandpass_2nd_order",
        "constraints": {
            "target_center_hz": 20000.0,
            "target_bw_hz": 4000.0,
            "filter_order": 2,
            "source_res_ohm": 50.0,
            "load_res_ohm": 1000.0,
            "fixed_ind_h": 10e-3,
            "vin_ac": 1.0,
            "vin_step": 0.5,
        },
    },
    "cs_amp": {
        "display_name": "Common-Source Amplifier",
        "specification": "Design a single-stage common-source amplifier for moderate gain.",
        "forced_topology": "common_source_res_load",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 20.0,
            "target_bw_hz": 1e6,
            "power_limit_mw": 2.0,
            "vin_dc": 0.75,
            "vin_ac": 1e-3,
            "load_cap_f": 1e-12,
            "target_vov_v": 0.2,
        },
    },
    "mirror": {
        "display_name": "Current Mirror",
        "specification": "Design a MOS current mirror to generate 100 uA output current.",
        "forced_topology": "current_mirror",
        "constraints": {
            "supply_v": 1.8,
            "target_iout_a": 100e-6,
            "mirror_ratio": 1.0,
            "compliance_v": 0.8,
            "target_vov_v": 0.2,
        },
    },
    "opamp": {
        "display_name": "2-Stage Op-Amp with Miller Compensation",
        "specification": "Design a two-stage op amp with 60 dB gain and 10 MHz UGBW.",
        "forced_topology": "two_stage_miller",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 60.0,
            "target_ugbw_hz": 10e6,
            "phase_margin_deg": 60.0,
            "load_cap_f": 1e-12,
            "power_limit_mw": 2.0,
            "target_slew_v_per_us": 5.0,
            "vin_ac": 1.0,
            "vin_step": 0.05,
            "vin_cm_dc": 0.9,
        },
    },
    "common_source": {
        "display_name": "Common-Source Amplifier",
        "specification": "Design a common-source amplifier.",
        "forced_topology": "common_source_res_load",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 18.0,
            "target_bw_hz": 2e6,
            "power_limit_mw": 2.0,
            "vin_dc": 0.75,
            "vin_ac": 1e-3,
            "load_cap_f": 0.5e-12,
            "target_vov_v": 0.2,
        },
    },
    "two_stage_common_source_res_load": {
        "display_name": "2-Stage Common-Source Amplifier with Resistive Load",
        "specification": "Design a two-stage common-source amplifier with resistive loads.",
        "forced_topology": "two_stage_miller",
        "demo_model": "behavioral_two_stage",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 45.0,
            "target_ugbw_hz": 5e6,
            "phase_margin_deg": 60.0,
            "load_cap_f": 1e-12,
            "power_limit_mw": 3.0,
            "target_slew_v_per_us": 3.0,
            "vin_ac": 1.0,
            "vin_step": 0.05,
        },
    },
    "common_drain": {
        "display_name": "Common-Drain Amplifier",
        "specification": "Design a common-drain source follower buffer.",
        "forced_topology": "common_drain",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.8,
            "target_gm_s": 2e-3,
            "target_vov_v": 0.18,
            "target_vout_q_v": 0.7,
            "vin_ac": 1e-3,
            "vin_step": 0.05,
            "load_cap_f": 1e-12,
        },
    },
    "common_gate": {
        "display_name": "Common-Gate Amplifier",
        "specification": "Design a common-gate amplifier.",
        "forced_topology": "common_gate",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.8,
            "target_gm_s": 1.5e-3,
            "target_vov_v": 0.2,
            "vin_dc": 0.2,
            "vin_ac": 1e-3,
            "vin_step": 0.02,
            "load_cap_f": 1e-12,
        },
    },
    "source_degenerated_amplifier": {
        "display_name": "Source-Degenerated Amplifier",
        "specification": "Design a source-degenerated common-source amplifier.",
        "forced_topology": "source_degenerated_cs",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 12.0,
            "target_bw_hz": 3e6,
            "power_limit_mw": 2.0,
            "vin_dc": 0.8,
            "vin_ac": 1e-3,
            "load_cap_f": 1e-12,
            "target_vov_v": 0.18,
        },
    },
    "common_source_active_load": {
        "display_name": "Common-Source Amplifier with Active Load",
        "specification": "Design a common-source amplifier using an active load.",
        "forced_topology": "common_source_active_load",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 10.0,
            "target_bw_hz": 3e6,
            "power_limit_mw": 2.0,
            "vin_dc": 0.75,
            "vin_ac": 1e-3,
            "load_cap_f": 1e-12,
            "target_vov_v": 0.18,
        },
    },
    "cascode_amp": {
        "display_name": "Cascode Amplifier using NMOS and Resistive Load",
        "specification": "Design a cascode amplifier using NMOS devices and a resistive load.",
        "forced_topology": "cascode_amplifier",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 8.0,
            "target_bw_hz": 2e6,
            "power_limit_mw": 2.5,
            "vin_dc": 0.7,
            "vin_ac": 1e-3,
            "load_cap_f": 1e-12,
            "target_vov_v": 0.16,
        },
    },
    "diff_pair": {
        "display_name": "1-Stage Differential Amplifier",
        "specification": "Design a one-stage differential amplifier.",
        "forced_topology": "diff_pair",
        "constraints": {
            "supply_v": 1.8,
            "power_limit_mw": 2.0,
            "vin_ac": 1e-3,
            "vicm_v": 0.9,
            "R_load_ohm": 5000.0,
            "target_vov_v": 0.2,
        },
    },
    "diode_connected_amplifier": {
        "display_name": "Diode-Connected Amplifier",
        "specification": "Design a diode-connected MOS amplifier.",
        "forced_topology": "diode_connected_stage",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 8.0,
            "power_limit_mw": 1.5,
            "vin_dc": 0.75,
            "vin_ac": 1e-3,
            "load_cap_f": 1e-12,
            "target_vov_v": 0.15,
        },
    },
    "mos_buffer": {
        "display_name": "Buffer Design using MOSFET",
        "specification": "Design a MOSFET-based buffer stage.",
        "forced_topology": "common_drain",
        "demo_model": "native",
        "constraints": {
            "target_gm_s": 2.5e-3,
            "target_vov_v": 0.18,
            "supply_v": 1.8,
            "target_vout_q_v": 0.75,
            "vin_ac": 1e-3,
            "vin_step": 0.05,
            "load_cap_f": 2e-12,
        },
    },
    "nand2": {
        "display_name": "2-Input NAND Gate",
        "specification": "Design a two-input NAND gate.",
        "forced_topology": "nand2_cmos",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.8,
            "load_cap_f": 10e-15,
        },
    },
    "sram6t": {
        "display_name": "6T SRAM Cell",
        "specification": "Design a six-transistor SRAM cell.",
        "forced_topology": "sram6t_cell",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.2,
        },
    },
    "two_stage_opamp_single_ended": {
        "display_name": "2-Stage Op-Amp with Differential Input and Single-Ended Output",
        "specification": "Design a two-stage op amp with differential input and single-ended output.",
        "forced_topology": "two_stage_miller",
        "demo_model": "behavioral_two_stage",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 58.0,
            "target_ugbw_hz": 8e6,
            "phase_margin_deg": 60.0,
            "load_cap_f": 1e-12,
            "power_limit_mw": 2.5,
            "target_slew_v_per_us": 4.0,
            "vin_ac": 1.0,
            "vin_step": 0.05,
        },
    },
    "fully_diff_amp_cmfb": {
        "display_name": "Fully Differential Amplifier with CMFB",
        "specification": "Design a fully differential amplifier with common-mode feedback.",
        "forced_topology": "diff_pair",
        "demo_model": "diff_proxy",
        "constraints": {
            "supply_v": 1.8,
            "power_limit_mw": 3.0,
            "vin_ac": 1e-3,
            "vicm_v": 0.9,
            "R_load_ohm": 8000.0,
            "target_vov_v": 0.18,
        },
    },
    "lc_oscillator": {
        "display_name": "Cross-Coupled LC Oscillator",
        "specification": "Design a cross-coupled LC oscillator.",
        "forced_topology": "lc_oscillator_cross_coupled",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.8,
            "target_osc_hz": 100e6,
            "L_tank_h": 100e-9,
            "tail_current_a": 100e-6,
            "r_tank_loss_ohm": 10000.0,
        },
    },
    "telescopic_cascode_opamp": {
        "display_name": "Telescopic Cascode Op Amplifier",
        "specification": "Design a telescopic cascode op amp.",
        "forced_topology": "two_stage_miller",
        "demo_model": "behavioral_opamp_proxy",
        "constraints": {
            "supply_v": 1.8,
            "target_gain_db": 65.0,
            "target_ugbw_hz": 12e6,
            "phase_margin_deg": 60.0,
            "load_cap_f": 0.8e-12,
            "power_limit_mw": 2.0,
            "target_slew_v_per_us": 4.0,
            "vin_ac": 1.0,
            "vin_step": 0.03,
        },
    },
    "bandgap_reference": {
        "display_name": "Bandgap Reference",
        "specification": "Design a bandgap reference with visible line-regulation and settling behavior.",
        "forced_topology": "bandgap_reference_core",
        "demo_model": "native",
        "constraints": {
            "supply_v": 1.8,
            "target_vref_v": 1.2,
            "area_ratio": 8.0,
            "R1_ohm": 5000.0,
            "i_core_a": 20e-6,
        },
    },
}

CASE_ALIASES = {
    "1": "common_source",
    "2": "two_stage_common_source_res_load",
    "3": "common_drain",
    "4": "common_gate",
    "5": "rc",
    "21": "butterworth_rlc_lowpass",
    "22": "rlc_highpass",
    "23": "rlc_bandpass",
    "6": "source_degenerated_amplifier",
    "7": "mirror",
    "8": "common_source_active_load",
    "9": "cascode_amp",
    "10": "diff_pair",
    "11": "diode_connected_amplifier",
    "12": "mos_buffer",
    "13": "nand2",
    "14": "opamp",
    "15": "sram6t",
    "16": "two_stage_opamp_single_ended",
    "17": "fully_diff_amp_cmfb",
    "18": "lc_oscillator",
    "19": "telescopic_cascode_opamp",
    "20": "bandgap_reference",
}


def resolve_case_name(case_name: str) -> str:
    key = (case_name or "").strip().lower()
    return CASE_ALIASES.get(key, key)


def get_demo_case(case_name: str):
    resolved = resolve_case_name(case_name)
    if resolved not in DEMO_CASES:
        available = ", ".join(sorted(DEMO_CASES))
        raise KeyError(f"Unknown DESIGN_CASE '{case_name}'. Available cases: {available}")
    case = dict(DEMO_CASES[resolved])
    case["case_key"] = resolved
    case["artifact_label"] = describe_case_for_artifacts(case)
    case["simulation_plan"] = build_case_simulation_plan(case)
    return case


def list_demo_cases():
    return [
        {
            "key": key,
            "display_name": value.get("display_name", key),
            "forced_topology": value.get("forced_topology"),
            "demo_model": value.get("demo_model", "native"),
            "artifact_label": describe_case_for_artifacts({"key": key, **value}),
            "simulation_plan": build_case_simulation_plan({"forced_topology": value.get("forced_topology"), **value}),
        }
        for key, value in sorted(DEMO_CASES.items())
    ]
