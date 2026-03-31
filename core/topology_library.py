TOPOLOGY_LIBRARY = {
    "rc_lowpass": {
        "name": "Single-Stage RC Low-Pass Filter",
        "category": "filter",
        "constraint_template": "filter_rc",
        "complexity": "low"
    },
    "current_mirror": {
        "name": "MOS Current Mirror",
        "category": "bias",
        "constraint_template": "bias_current_mirror",
        "complexity": "low"
    },
    "wilson_current_mirror": {
        "name": "Wilson Current Mirror",
        "category": "bias",
        "constraint_template": "bias_current_mirror_precision",
        "complexity": "medium"
    },
    "cascode_current_mirror": {
        "name": "Cascode Current Mirror",
        "category": "bias",
        "constraint_template": "bias_current_mirror_high_output_resistance",
        "complexity": "medium"
    },
    "common_source_res_load": {
        "name": "Common-Source Amplifier with Resistive Load",
        "category": "amplifier",
        "constraint_template": "amplifier_single_stage",
        "complexity": "medium"
    },
    "diff_pair": {
        "name": "MOS Differential Pair",
        "category": "amplifier",
        "constraint_template": "amplifier_differential",
        "complexity": "medium"
    },
    "bjt_diff_pair": {
        "name": "BJT Differential Pair",
        "category": "amplifier",
        "constraint_template": "amplifier_differential_bjt",
        "complexity": "medium"
    },
    "gm_stage": {
        "name": "Transconductance Stage",
        "category": "analog_block",
        "constraint_template": "transconductor",
        "complexity": "medium"
    },
    "two_stage_miller": {
        "name": "Two-Stage Op-Amp with Miller Compensation",
        "category": "opamp",
        "constraint_template": "opamp_two_stage",
        "complexity": "high"
    },
    "folded_cascode_opamp": {
        "name": "Folded Cascode Op-Amp",
        "category": "opamp",
        "constraint_template": "opamp_folded_cascode",
        "complexity": "high"
    },
    "comparator": {
        "name": "Differential Comparator",
        "category": "mixed_signal",
        "constraint_template": "comparator",
        "complexity": "medium"
    }
}
