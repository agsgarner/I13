# I13/core/topology_library.py

TOPOLOGY_LIBRARY = {
    "rc_lowpass": {
        "name": "Single-Stage RC Low-Pass Filter",
        "category": "filter",
        "constraint_template": "filter_rc",
        "complexity": "low"
    },

    "common_source_res_load": {
        "name": "Common-Source Amplifier with Resistive Load",
        "category": "amplifier",
        "constraint_template": "amplifier_single_stage",
        "complexity": "medium"
    },

    "diff_pair": {
        "name": "Differential Pair",
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

    "two_stage_miller": {
        "name": "Two-Stage Op-Amp with Miller Compensation",
        "category": "opamp",
        "constraint_template": "opamp_two_stage",
        "complexity": "high"
    }
}
