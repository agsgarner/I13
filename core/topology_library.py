TOPOLOGY_LIBRARY = {

    "common_source": {
        "name": "Common-Source Amplifier",
        "category": "amplifier",
        "constraint_template": "amplifier_single_stage",
        "complexity": "low"
    },

    "common_source_res_load": {
        "name": "Common-Source w/ Resistive Load",
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
    "common_drain": {
        "name": "Common-Drain Source Follower",
        "category": "amplifier",
        "constraint_template": "source_follower",
        "complexity": "medium"
    },
    "common_gate": {
        "name": "Common-Gate Amplifier",
        "category": "amplifier",
        "constraint_template": "common_gate_amp",
        "complexity": "medium"
    },
    "source_degenerated_cs": {
        "name": "Source-Degenerated Common-Source Amplifier",
        "category": "amplifier",
        "constraint_template": "amplifier_source_degenerated",
        "complexity": "medium"
    },
    "common_source_active_load": {
        "name": "Common-Source Amplifier with Active Load",
        "category": "amplifier",
        "constraint_template": "amplifier_active_load",
        "complexity": "medium"
    },
    "diode_connected_stage": {
        "name": "Diode-Connected MOS Amplifier",
        "category": "amplifier",
        "constraint_template": "amplifier_active_load",
        "complexity": "medium"
    },
    "cascode_amplifier": {
        "name": "NMOS Cascode Amplifier",
        "category": "amplifier",
        "constraint_template": "amplifier_cascode",
        "complexity": "high"
    },
    "nand2_cmos": {
        "name": "CMOS 2-Input NAND Gate",
        "category": "digital",
        "constraint_template": "digital_cmos_gate",
        "complexity": "medium"
    },
    "sram6t_cell": {
        "name": "6T SRAM Cell",
        "category": "memory",
        "constraint_template": "memory_sram_cell",
        "complexity": "high"
    },
    "lc_oscillator_cross_coupled": {
        "name": "Cross-Coupled LC Oscillator",
        "category": "oscillator",
        "constraint_template": "oscillator_lc",
        "complexity": "high"
    },
    "bandgap_reference_core": {
        "name": "Bandgap Reference Core",
        "category": "reference",
        "constraint_template": "reference_bandgap",
        "complexity": "high"
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
