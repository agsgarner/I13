# I13/core/analog_defaults.py

ANALOG_DEFAULTS = {
    "process": {
        "supply_v": 1.8,
        "L_min_m": 180e-9,
        "mu_cox_a_per_v2": 200e-6,
        "lambda_1_per_v": 0.02,
        "vth_n_v": 0.5,
        "target_vov_v": 0.2,
    },
    "methodology": {
        "gm_id_target_s_per_a_moderate": 12.0,
        "gm_id_target_s_per_a_low_power": 16.0,
        "gm_id_target_s_per_a_high_speed": 8.0,
        "ro_floor_ohm": 1e4,
    },
    "common_source": {
        "target_vout_q_ratio": 0.5,
        "vin_ac_small_signal_v": 1e-3,
        "rd_initial_ohm": 5000.0,
    },
    "current_mirror": {
        "mirror_ratio": 1.0,
        "compliance_v": 0.8,
    },
    "filters": {
        "response_family": "butterworth",
        "filter_order": 2,
        "source_res_ohm": 50.0,
        "load_res_ohm": 10000.0,
        "passband_gain_db": 0.0,
    },
    "opamp": {
        "phase_margin_deg": 60.0,
        "target_slew_v_per_us": 5.0,
    },
    "topology_selection": {
        "max_stage_count": 4,
        "enable_llm_stage_planning": True,
    },
}
