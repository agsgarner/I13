TOPOLOGY_ALIASES = {
    "diff_pair_resistor_load": "diff_pair",
    "telescopic_cascode_opamp_core": "two_stage_miller",
    "folded_cascode_opamp_core": "folded_cascode_opamp",
    "adc_input_buffer": "common_drain",
    "adc_anti_alias_rc": "rc_lowpass",
    "adc_reference_buffer": "common_drain",
    "dac_output_buffer": "common_drain",
    "dac_reference_conditioning": "rc_lowpass",
    "ldo_error_amp_core": "two_stage_miller",
    "compensation_network_helper": "rc_lowpass",
    "active_filter_stage": "rlc_lowpass_2nd_order",
    "latched_comparator": "comparator",
}


def canonical_topology_key(topology_key: str) -> str:
    if not topology_key:
        return topology_key
    return TOPOLOGY_ALIASES.get(topology_key, topology_key)
