# I13/core/topology_library.py

TOPOLOGY_LIBRARY = {

    "common_source": {
        "name": "Common-Source Amplifier",
        "category": "amplifier",
        "constraint_template": "amplifier_single_stage",
        "complexity": "low"
    },

    "two_stage_cs_res_load": {
        "name": "2-Stage Common-Source w/ Resistive Load",
        "category": "amplifier",
        "constraint_template": "amplifier_two_stage",
        "complexity": "medium"
    },

    "common_drain": {
        "name": "Common-Drain Amplifier",
        "category": "buffer",
        "constraint_template": "amplifier_single_stage",
        "complexity": "low"
    },

    "common_gate": {
        "name": "Common-Gate Amplifier",
        "category": "amplifier",
        "constraint_template": "amplifier_single_stage",
        "complexity": "low"
    },

    "rc_lowpass": {
        "name": "Single-Stage RC Low-Pass Filter",
        "category": "filter",
        "constraint_template": "filter_rc",
        "complexity": "low"
    },

    "source_degenerated_cs": {
        "name": "Source Degenerated Amplifier",
        "category": "amplifier",
        "constraint_template": "amplifier_single_stage",
        "complexity": "medium"
    },

    "current_mirror": {
        "name": "Current Mirror",
        "category": "bias",
        "constraint_template": "bias_current_mirror",
        "complexity": "low"
    },

    "cs_active_load": {
        "name": "Common-Source w/ Active Load",
        "category": "amplifier",
        "constraint_template": "amplifier_single_stage",
        "complexity": "medium"
    },

    "cascode_res_load": {
        "name": "Cascode w/ Resistive Load",
        "category": "amplifier",
        "constraint_template": "amplifier_single_stage",
        "complexity": "medium"
    },

    "diff_pair": {
        "name": "1-Stage Differential Amplifier",
        "category": "amplifier",
        "constraint_template": "amplifier_single_stage",
        "complexity": "medium"
    },

    "diode_connected": {
        "name": "Diode-Connected Amplifier",
        "category": "bias",
        "constraint_template": "amplifier_single_stage",
        "complexity": "low"
    },

    "mos_buffer": {
        "name": "MOSFET Buffer",
        "category": "buffer",
        "constraint_template": "amplifier_single_stage",
        "complexity": "low"
    },

    "two_stage_miller": {
        "name": "2-Stage Op-Amp w/ Miller Compensation",
        "category": "opamp",
        "constraint_template": "opamp_two_stage",
        "complexity": "high"
    },

    "fully_diff_cmfb": {
        "name": "Fully Differential Amplifier w/ CMFB",
        "category": "opamp",
        "constraint_template": "opamp_two_stage",
        "complexity": "high"
    },

    "telescopic_opamp": {
        "name": "Telescopic Cascode Op-Amp",
        "category": "opamp",
        "constraint_template": "amplifier_single_stage",
        "complexity": "high"
    },

    "lc_oscillator": {
        "name": "Cross-Coupled LC Oscillator",
        "category": "oscillator",
        "constraint_template": "oscillator_lc",
        "complexity": "high"
    },

    "bandgap_reference": {
        "name": "Bandgap Reference",
        "category": "reference",
        "constraint_template": "reference_bandgap",
        "complexity": "high"
    }
}