from __future__ import annotations

from copy import deepcopy

from core.demo_catalog import (
    READINESS_DISABLED,
    READINESS_EXPERIMENTAL,
    READINESS_STABLE_DEMO,
    READINESS_STABLE_NO_SWEEP,
    get_demo_case,
    list_demo_cases,
    resolve_case_name,
)
from core.topology_library import TOPOLOGY_LIBRARY


UI_CATEGORY_LABELS = {
    "filter": "Filters / Signal Conditioning",
    "amplifier": "MOS Amplifiers",
    "bias": "Current Mirrors / Bias",
    "opamp": "Op-Amps",
    "reference": "References / Power",
    "power_support": "References / Power",
    "adc_support": "ADC/DAC Interfaces",
    "dac_support": "ADC/DAC Interfaces",
    "sensor_frontend": "Sensor Front Ends",
    "mixed_signal": "Mixed-Signal Extras",
    "digital": "Mixed-Signal Extras",
    "memory": "Mixed-Signal Extras",
    "oscillator": "Mixed-Signal Extras",
    "composite": "Sensor Front Ends",
    "analog_block": "Differential / gm Stages",
}


CASE_SWEEP_SCHEMAS = {
    "rc": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "target_fc_hz",
        "sweep_parameters": {
            "target_fc_hz": {
                "label": "Target cutoff (Hz)",
                "min": 10.0,
                "max": 1.0e7,
                "step": 100.0,
                "default": 1000.0,
                "default_points": [500.0, 1000.0, 5000.0],
                "metric_keys": ["fc_hz", "fc_hz_from_ac", "bandwidth_hz"],
                "requirement_keys": ["fc_hz", "cutoff_hz", "bandwidth_hz"],
            },
            "fixed_cap_f": {
                "label": "Fixed capacitor (F)",
                "min": 1e-12,
                "max": 1e-3,
                "step": 1e-9,
                "default": 10e-9,
                "default_points": [4.7e-9, 10e-9, 22e-9],
                "metric_keys": ["fc_hz", "fc_hz_from_ac"],
                "requirement_keys": ["fc_hz", "cutoff_hz"],
            },
        },
        "required_simulation_modes": ["ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
    "rlc_bandpass": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "target_center_hz",
        "sweep_parameters": {
            "target_center_hz": {
                "label": "Target center frequency (Hz)",
                "min": 10.0,
                "max": 1.0e8,
                "step": 100.0,
                "default": 20000.0,
                "default_points": [12000.0, 20000.0, 32000.0],
                "metric_keys": ["center_hz", "peak_frequency_hz", "bandwidth_hz", "q_factor"],
                "requirement_keys": ["center_hz", "bandwidth_hz"],
            },
            "quality_factor_q": {
                "label": "Quality factor Q",
                "min": 0.5,
                "max": 50.0,
                "step": 0.5,
                "default": 3.0,
                "default_points": [1.5, 3.0, 5.0],
                "metric_keys": ["q_factor", "center_hz", "bandwidth_hz"],
                "requirement_keys": ["center_hz", "bandwidth_hz"],
            },
        },
        "required_simulation_modes": ["ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
    "common_source": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "target_gain_db",
        "sweep_parameters": {
            "target_gain_db": {
                "label": "Target gain (dB)",
                "min": 1.0,
                "max": 80.0,
                "step": 1.0,
                "default": 18.0,
                "default_points": [14.0, 18.0, 24.0],
                "metric_keys": ["gain_db", "bandwidth_hz", "power_mw"],
                "requirement_keys": ["gain_db", "bandwidth_hz", "power_mw"],
            },
            "target_bw_hz": {
                "label": "Target bandwidth (Hz)",
                "min": 1e3,
                "max": 1e9,
                "step": 1e5,
                "default": 2e6,
                "default_points": [1e6, 2e6, 5e6],
                "metric_keys": ["bandwidth_hz", "gain_db", "power_mw"],
                "requirement_keys": ["bandwidth_hz", "gain_db", "power_mw"],
            },
        },
        "required_simulation_modes": ["op", "ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
    "mirror": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "target_iout_a",
        "sweep_parameters": {
            "target_iout_a": {
                "label": "Target output current (A)",
                "min": 1e-6,
                "max": 10e-3,
                "step": 10e-6,
                "default": 100e-6,
                "default_points": [80e-6, 100e-6, 150e-6],
                "metric_keys": ["iout_a", "output_current_a", "ratio_error_percent"],
                "requirement_keys": ["iout_a", "compliance_voltage_v"],
            },
            "reference_current_a": {
                "label": "Reference current (A)",
                "min": 1e-6,
                "max": 10e-3,
                "step": 10e-6,
                "default": 100e-6,
                "default_points": [80e-6, 100e-6, 150e-6],
                "metric_keys": ["iout_a", "output_current_a", "ratio_error_percent"],
                "requirement_keys": ["iout_a", "compliance_voltage_v"],
            },
            "mirror_ratio": {
                "label": "Mirror ratio",
                "min": 0.1,
                "max": 20.0,
                "step": 0.1,
                "default": 1.0,
                "default_points": [0.5, 1.0, 2.0],
                "metric_keys": ["mirror_ratio_measured", "ratio_error_percent", "iout_a"],
                "requirement_keys": ["iout_a", "compliance_voltage_v"],
            },
        },
        "required_simulation_modes": ["op", "dc"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["dc_plot"],
    },
    "folded_cascode_opamp": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "target_gain_db",
        "sweep_parameters": {
            "target_gain_db": {
                "label": "Target gain (dB)",
                "min": 20.0,
                "max": 100.0,
                "step": 1.0,
                "default": 62.0,
                "default_points": [56.0, 62.0, 68.0],
                "metric_keys": ["gain_db", "ugbw_hz", "power_mw", "phase_margin_deg"],
                "requirement_keys": ["gain_db", "ugbw_hz", "power_mw"],
            },
            "target_ugbw_hz": {
                "label": "Target UGBW (Hz)",
                "min": 1e5,
                "max": 1e9,
                "step": 1e6,
                "default": 15e6,
                "default_points": [8e6, 15e6, 25e6],
                "metric_keys": ["ugbw_hz", "gain_db", "power_mw", "phase_margin_deg"],
                "requirement_keys": ["ugbw_hz", "gain_db", "power_mw"],
            },
            "load_cap_f": {
                "label": "Load capacitor (F)",
                "min": 1e-15,
                "max": 1e-8,
                "step": 1e-12,
                "default": 1e-12,
                "default_points": [0.5e-12, 1e-12, 2e-12],
                "metric_keys": ["ugbw_hz", "phase_margin_deg", "power_mw"],
                "requirement_keys": ["ugbw_hz", "gain_db", "power_mw"],
            },
        },
        "required_simulation_modes": ["op", "ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
    "comparator": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "input_overdrive_v",
        "sweep_parameters": {
            "input_overdrive_v": {
                "label": "Input overdrive (V)",
                "min": 1e-3,
                "max": 0.2,
                "step": 1e-3,
                "default": 20e-3,
                "default_points": [10e-3, 20e-3, 30e-3],
                "metric_keys": ["decision_delay_s", "decision_correct", "decision_swing_v"],
                "requirement_keys": ["decision_delay_s", "decision_correct"],
            },
            "target_decision_delay_s": {
                "label": "Decision delay target (s)",
                "min": 1e-12,
                "max": 1e-6,
                "step": 1e-9,
                "default": 2e-9,
                "default_points": [1e-9, 2e-9, 3e-9],
                "metric_keys": ["decision_delay_s", "decision_correct"],
                "requirement_keys": ["decision_delay_s", "decision_correct"],
            },
        },
        "required_simulation_modes": ["tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["tran_plot"],
    },
    "bandgap_reference": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "target_vref_v",
        "sweep_parameters": {
            "target_vref_v": {
                "label": "Target Vref (V)",
                "min": 0.8,
                "max": 1.4,
                "step": 0.01,
                "default": 1.2,
                "default_points": [1.15, 1.2, 1.25],
                "metric_keys": ["vref_v", "line_regulation_mv_per_v", "power_mw"],
                "requirement_keys": ["vref_v", "line_regulation_mv_per_v"],
            },
            "supply_v": {
                "label": "Supply voltage (V)",
                "min": 1.2,
                "max": 3.3,
                "step": 0.1,
                "default": 1.8,
                "default_points": [1.6, 1.8, 2.0],
                "metric_keys": ["vref_v", "line_regulation_mv_per_v", "power_mw"],
                "requirement_keys": ["vref_v", "line_regulation_mv_per_v"],
            },
        },
        "required_simulation_modes": ["op", "dc", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["dc_plot", "tran_plot"],
    },
    "mos_buffer": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "load_cap_f",
        "sweep_parameters": {
            "load_cap_f": {
                "label": "Load capacitor (F)",
                "min": 1e-15,
                "max": 1e-8,
                "step": 1e-12,
                "default": 2e-12,
                "default_points": [1e-12, 2e-12, 4e-12],
                "metric_keys": ["gain_db", "output_swing_v", "power_mw", "common_mode_final_v"],
                "requirement_keys": ["gain_db", "power_mw", "output_quiescent_v", "output_swing_v", "common_mode_final_v"],
            },
            "target_vout_q_v": {
                "label": "Target output quiescent (V)",
                "min": 0.5,
                "max": 1.0,
                "step": 0.01,
                "default": 0.75,
                "default_points": [0.65, 0.75, 0.85],
                "metric_keys": ["common_mode_final_v", "output_quiescent_v", "gain_db", "output_swing_v"],
                "requirement_keys": ["output_quiescent_v", "common_mode_final_v", "gain_db", "output_swing_v"],
            }
        },
        "required_simulation_modes": ["op", "ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
    "common_drain": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "load_cap_f",
        "sweep_parameters": {
            "load_cap_f": {
                "label": "Load capacitor (F)",
                "min": 1e-15,
                "max": 1e-8,
                "step": 1e-12,
                "default": 1e-12,
                "default_points": [1e-12, 2e-12, 4e-12],
                "metric_keys": ["gain_db", "output_swing_v", "power_mw", "common_mode_final_v"],
                "requirement_keys": ["gain_db", "power_mw", "output_quiescent_v", "output_swing_v", "common_mode_final_v"],
            },
            "target_vout_q_v": {
                "label": "Target output quiescent (V)",
                "min": 0.5,
                "max": 1.0,
                "step": 0.01,
                "default": 0.7,
                "default_points": [0.6, 0.7, 0.8],
                "metric_keys": ["common_mode_final_v", "output_quiescent_v", "gain_db", "output_swing_v"],
                "requirement_keys": ["output_quiescent_v", "common_mode_final_v", "gain_db", "output_swing_v"],
            },
        },
        "required_simulation_modes": ["op", "ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
    "common_gate": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "load_cap_f",
        "sweep_parameters": {
            "load_cap_f": {
                "label": "Load capacitor (F)",
                "min": 1e-15,
                "max": 1e-8,
                "step": 1e-12,
                "default": 1e-12,
                "default_points": [0.5e-12, 1e-12, 2e-12],
                "metric_keys": ["gain_db", "bandwidth_hz", "power_mw", "output_swing_v"],
                "requirement_keys": ["gain_db", "bandwidth_hz", "power_mw"],
            },
            "target_gain_db": {
                "label": "Target gain (dB)",
                "min": 2.0,
                "max": 20.0,
                "step": 0.5,
                "default": 10.0,
                "default_points": [8.0, 10.0, 12.0],
                "metric_keys": ["gain_db", "bandwidth_hz", "power_mw"],
                "requirement_keys": ["gain_db", "bandwidth_hz", "power_mw"],
            },
        },
        "required_simulation_modes": ["op", "ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
    "cascode_amp": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "load_cap_f",
        "sweep_parameters": {
            "load_cap_f": {
                "label": "Load capacitor (F)",
                "min": 1e-15,
                "max": 1e-8,
                "step": 1e-12,
                "default": 1e-12,
                "default_points": [0.5e-12, 1e-12, 2e-12],
                "metric_keys": ["gain_db", "bandwidth_hz", "ugbw_hz", "power_mw"],
                "requirement_keys": ["gain_db", "bandwidth_hz", "power_mw"],
            },
            "target_gain_db": {
                "label": "Target gain (dB)",
                "min": 4.0,
                "max": 12.0,
                "step": 0.5,
                "default": 8.0,
                "default_points": [6.0, 8.0, 9.0],
                "metric_keys": ["gain_db", "bandwidth_hz", "ugbw_hz", "power_mw"],
                "requirement_keys": ["gain_db", "bandwidth_hz", "power_mw"],
            },
        },
        "required_simulation_modes": ["op", "ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
    "source_degenerated_amplifier": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "target_gain_db",
        "sweep_parameters": {
            "target_gain_db": {
                "label": "Target gain (dB)",
                "min": 6.0,
                "max": 20.0,
                "step": 0.5,
                "default": 12.0,
                "default_points": [10.0, 12.0, 14.0],
                "metric_keys": ["gain_db", "bandwidth_hz", "power_mw", "output_swing_v"],
                "requirement_keys": ["gain_db", "bandwidth_hz", "power_mw"],
            },
            "load_cap_f": {
                "label": "Load capacitor (F)",
                "min": 1e-15,
                "max": 1e-8,
                "step": 1e-12,
                "default": 1e-12,
                "default_points": [0.5e-12, 1e-12, 2e-12],
                "metric_keys": ["gain_db", "bandwidth_hz", "power_mw", "output_swing_v"],
                "requirement_keys": ["gain_db", "bandwidth_hz", "power_mw"],
            },
        },
        "required_simulation_modes": ["op", "ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
    "common_source_active_load": {
        "readiness": READINESS_STABLE_DEMO,
        "default_sweep_parameter": "load_cap_f",
        "sweep_parameters": {
            "load_cap_f": {
                "label": "Load capacitor (F)",
                "min": 1e-15,
                "max": 1e-8,
                "step": 1e-12,
                "default": 1e-12,
                "default_points": [1e-12, 2e-12, 4e-12],
                "metric_keys": ["gain_db", "bandwidth_hz", "power_mw", "output_swing_v"],
                "requirement_keys": ["gain_db", "bandwidth_hz", "power_mw"],
            },
            "target_gain_db": {
                "label": "Target gain (dB)",
                "min": 6.0,
                "max": 10.0,
                "step": 0.5,
                "default": 8.0,
                "default_points": [7.0, 8.0, 9.0],
                "metric_keys": ["gain_db", "bandwidth_hz", "power_mw"],
                "requirement_keys": ["gain_db", "bandwidth_hz", "power_mw"],
            },
        },
        "required_simulation_modes": ["op", "ac", "tran"],
        "required_artifacts": ["generated_netlist", "final_report", "schematic_png"],
        "required_any_plots": ["ac_plot", "tran_plot"],
    },
}


FINAL_STATUS_FAILS = {"simulation_failed", "netlist_failed", "orchestration_failed"}


def list_ui_cases(*, include_experimental: bool = False, sponsor_demo_only: bool = False) -> list[dict]:
    rows = []
    for item in list_demo_cases():
        case_key = item["key"]
        readiness = item.get("readiness", READINESS_EXPERIMENTAL)
        if readiness == READINESS_DISABLED:
            continue
        if sponsor_demo_only and readiness != READINESS_STABLE_DEMO:
            continue
        if (not include_experimental) and readiness in {READINESS_EXPERIMENTAL}:
            continue
        case = get_demo_case(case_key)
        rows.append(
            {
                **item,
                "display_name": case.get("display_name", case_key),
                "forced_topology": case.get("forced_topology"),
                "category": case_ui_category(case_key),
                "sweep_schema": deepcopy(CASE_SWEEP_SCHEMAS.get(case_key) or {}),
            }
        )
    rows.sort(key=lambda x: (x.get("category") or "", x.get("display_name") or "", x.get("key") or ""))
    return rows


def case_ui_category(case_key: str) -> str:
    case = get_demo_case(case_key)
    topology = case.get("forced_topology")
    topo_meta = TOPOLOGY_LIBRARY.get(topology) or {}
    topo_category = topo_meta.get("category", "")
    return UI_CATEGORY_LABELS.get(topo_category, "Mixed-Signal Extras")


def get_case_sweep_schema(case_name: str) -> dict:
    resolved = resolve_case_name(case_name)
    return deepcopy(CASE_SWEEP_SCHEMAS.get(resolved) or {})


def sweepable_parameters(case_name: str) -> list[str]:
    schema = get_case_sweep_schema(case_name)
    return list((schema.get("sweep_parameters") or {}).keys())


def default_sweep_parameter(case_name: str) -> str | None:
    schema = get_case_sweep_schema(case_name)
    if schema.get("default_sweep_parameter"):
        return schema["default_sweep_parameter"]
    params = sweepable_parameters(case_name)
    return params[0] if params else None


def apply_sweep_value(case_name: str, constraints: dict, sweep_param: str, value: float) -> dict:
    resolved = resolve_case_name(case_name)
    updated = dict(constraints or {})
    updated[sweep_param] = float(value)

    if resolved == "mirror":
        if sweep_param == "reference_current_a":
            ratio = float(updated.get("mirror_ratio", 1.0))
            updated["target_iout_a"] = float(value) * ratio
        elif sweep_param == "mirror_ratio":
            ref = float(updated.get("reference_current_a", updated.get("target_iout_a", 100e-6)))
            updated["target_iout_a"] = ref * float(value)

    if resolved == "rlc_bandpass" and sweep_param == "quality_factor_q":
        center = float(updated.get("target_center_hz", 20000.0))
        updated["target_bw_hz"] = center / max(float(value), 1e-12)

    return updated


def extract_measured_metric(final_state: dict, case_name: str, sweep_param: str) -> tuple[str | None, float | None]:
    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or {}
    extracted = verification.get("extracted_metrics") or {}
    schema = get_case_sweep_schema(case_name)
    param_meta = ((schema.get("sweep_parameters") or {}).get(sweep_param) or {})
    for key in param_meta.get("metric_keys") or []:
        value = extracted.get(key)
        if value is None:
            value = sim.get(key)
        if value is not None:
            return key, value
    for key, value in extracted.items():
        if value is not None:
            return key, value
    return None, None


def evaluate_sweep_outcome(final_state: dict, case_name: str, sweep_param: str, row: dict | None = None) -> dict:
    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or {}
    schema = get_case_sweep_schema(case_name)
    param_meta = ((schema.get("sweep_parameters") or {}).get(sweep_param) or {})
    requirement_keys = set(param_meta.get("requirement_keys") or [])
    requirement_rows = [item for item in (verification.get("requirement_evaluations") or []) if item.get("requirement") in requirement_keys]

    missing_artifacts = []
    row = row or {}
    for field in schema.get("required_artifacts") or []:
        if not row.get(field):
            missing_artifacts.append(field)
    if (schema.get("required_any_plots") or []) and not any(row.get(name) for name in schema.get("required_any_plots") or []):
        missing_artifacts.append("any_plot")

    failed = any(item.get("status") == "fail" for item in requirement_rows)
    passed = bool(requirement_rows) and all(item.get("status") == "pass" for item in requirement_rows)

    if sim.get("simulation_skipped"):
        status = "SIMULATION MISSING"
    elif final_state.get("status") in FINAL_STATUS_FAILS:
        # Some designs converge and verify successfully but later refinement bookkeeping
        # can still end with orchestration_failed. Preserve the verified verdict here.
        if final_state.get("status") == "orchestration_failed" and verification.get("final_status") == "pass":
            status = "PASSED" if passed else "PARTIAL"
        else:
            status = "FAILED"
    elif verification.get("final_status") == "fail":
        status = "FAILED"
    else:
        if failed:
            status = "FAILED"
        elif passed:
            status = "PASSED"
        elif verification.get("final_status") == "pass":
            status = "PASSED"
        elif verification.get("final_status") == "partial":
            status = "PARTIAL"
        else:
            status = "NOT TESTED"

    if missing_artifacts:
        if status == "PASSED":
            status = "ARTIFACT MISSING"
        elif status in {"PARTIAL", "NOT TESTED"}:
            status = "ARTIFACT MISSING"

    return {
        "status": status,
        "missing_artifacts": missing_artifacts,
        "requirement_rows": requirement_rows,
        "overall_verdict": verification.get("overall_verdict"),
        "verification_status": verification.get("final_status"),
    }
