import json
import os
import shutil

from core.metric_extractors import (
    extract_ac_metrics,
    extract_current_mirror_dc_metrics,
    extract_dc_metrics,
    extract_line_regulation_metrics,
    extract_noise_metrics_from_text,
    extract_transient_metrics,
)


FAILURE_CATEGORY_ORDER = [
    "topology_mismatch",
    "bad_bias_point",
    "gain_miss",
    "bandwidth_miss",
    "unstable_or_poor_phase_margin",
    "power_too_high",
    "output_swing_violation",
    "common_mode_violation",
    "startup_failure",
    "convergence_failure",
]

REQUIREMENT_NAMES = {
    "gain_db",
    "bandwidth_hz",
    "ugbw_hz",
    "phase_margin_deg",
    "power_mw",
    "gm_s",
    "output_quiescent_v",
    "output_swing_v",
    "common_mode_final_v",
    "max_slew_v_per_us",
    "vref_v",
    "line_regulation_mv_per_v",
    "iout_a",
    "compliance_voltage_v",
    "onoise_total_vrms",
    "decision_delay_s",
    "decision_correct",
    "write_ok",
    "startup_ok",
    "oscillation_hz",
    "cutoff_hz",
    "center_hz",
    "transimpedance_ohm",
}


def collect_analysis_metrics(
    topology,
    plan,
    constraints,
    sizing,
    sim,
    analysis_data=None,
    op_point_results=None,
    log_text="",
):
    analysis_data = dict(analysis_data or {})
    per_analysis = {}
    planned_analyses = set(plan.get("analyses") or [])

    op_characterization = ((op_point_results or {}).get("characterization") or {})
    op_metrics = {}
    if op_characterization:
        op_metrics.update(op_characterization)
        near_triode = op_characterization.get("near_triode_devices") or []
        op_metrics["bias_ok"] = len(near_triode) == 0
    if sim.get("supply_current_a") is not None:
        op_metrics["supply_current_a"] = sim.get("supply_current_a")
    if sim.get("power_mw") is not None:
        op_metrics["power_mw"] = sim.get("power_mw")
    if sim.get("op_summary"):
        op_metrics["op_summary"] = sim.get("op_summary")
    op_executed = bool(op_metrics) or bool(op_point_results) or bool(sim.get("log_path"))
    per_analysis["op"] = {
        "planned": "op" in planned_analyses,
        "enabled": _analysis_enabled(plan, "op"),
        "executed": op_executed,
        "execution_kind": _execution_kind("op" in planned_analyses, op_executed),
        "metrics": op_metrics,
        "artifacts": _artifact_refs(sim, ["log_path"]),
    }

    if topology in {
        "current_mirror",
        "wilson_current_mirror",
        "cascode_current_mirror",
        "wide_swing_current_mirror",
        "widlar_current_mirror",
    }:
        dc_metrics = extract_current_mirror_dc_metrics(
            analysis_data.get("dc_data"),
            target_current_a=constraints.get("target_iout_a"),
        )
    else:
        dc_metrics = extract_dc_metrics(analysis_data.get("dc_data"))
    if topology == "bandgap_reference_core":
        dc_metrics.update(extract_line_regulation_metrics(analysis_data.get("dc_data")))
    if sim.get("iout_a") is not None:
        dc_metrics.setdefault("iout_a", sim.get("iout_a"))
    if sim.get("vref_v") is not None:
        dc_metrics.setdefault("vref_v", sim.get("vref_v"))
    dc_executed = bool((analysis_data.get("dc_data") or {}).get("x"))
    per_analysis["dc"] = {
        "planned": "dc" in planned_analyses,
        "enabled": _analysis_enabled(plan, "dc"),
        "executed": dc_executed,
        "execution_kind": _execution_kind("dc" in planned_analyses, dc_executed),
        "metrics": dc_metrics,
        "artifacts": _artifact_refs(sim, ["dc_csv", "dc_plot"]),
    }

    ac_metrics = extract_ac_metrics(
        analysis_data.get("ac_data"),
        input_ac_mag=float(analysis_data.get("input_ac_mag", 1.0)),
        phase_data=analysis_data.get("ac_phase_data"),
    )
    for key in (
        "gain_db",
        "bandwidth_hz",
        "ugbw_hz",
        "fc_hz",
        "center_hz",
        "q_factor",
        "phase_margin_deg",
    ):
        if sim.get(key) is not None:
            ac_metrics[key] = sim.get(key)
    if (sim.get("ac_characterization") or {}).get("response_shape") is not None:
        ac_metrics["response_shape"] = (sim.get("ac_characterization") or {}).get("response_shape")
    ac_executed = bool((analysis_data.get("ac_data") or {}).get("x"))
    per_analysis["ac"] = {
        "planned": "ac" in planned_analyses,
        "enabled": _analysis_enabled(plan, "ac"),
        "executed": ac_executed,
        "execution_kind": _execution_kind("ac" in planned_analyses, ac_executed),
        "metrics": ac_metrics,
        "artifacts": _artifact_refs(sim, ["ac_csv", "ac_phase_csv", "ac_plot"]),
    }

    tran_metrics = extract_transient_metrics(
        analysis_data.get("tran_out_data"),
        tran_in_data=analysis_data.get("tran_in_data"),
        tran_outn_data=analysis_data.get("tran_outn_data"),
    )
    for key in (
        "oscillation_hz",
        "decision_delay_s",
        "decision_correct",
        "decision_swing_v",
        "q_final_v",
        "qb_final_v",
        "write_ok",
        "transient_gain_db",
    ):
        if sim.get(key) is not None:
            tran_metrics[key] = sim.get(key)
    if sim.get("transient_characterization"):
        tran_metrics.update(sim.get("transient_characterization") or {})
    tran_executed = bool((analysis_data.get("tran_out_data") or {}).get("x"))
    per_analysis["tran"] = {
        "planned": "tran" in planned_analyses,
        "enabled": _analysis_enabled(plan, "tran"),
        "executed": tran_executed,
        "execution_kind": _execution_kind("tran" in planned_analyses, tran_executed),
        "metrics": tran_metrics,
        "artifacts": _artifact_refs(
            sim,
            [
                "tran_in_csv",
                "tran_out_csv",
                "tran_outn_csv",
                "tran_diff_csv",
                "tran_plot",
            ],
        ),
    }

    noise_metrics = extract_noise_metrics_from_text(log_text or "")
    noise_executed = bool(noise_metrics) or ("noise" in str(log_text).lower())
    per_analysis["noise"] = {
        "planned": "noise" in planned_analyses,
        "enabled": _analysis_enabled(plan, "noise"),
        "executed": noise_executed,
        "execution_kind": _execution_kind("noise" in planned_analyses, noise_executed),
        "metrics": noise_metrics,
        "artifacts": _artifact_refs(sim, ["log_path"]),
    }

    flat_metrics = {}
    for key in (
        "gain_db",
        "bandwidth_hz",
        "ugbw_hz",
        "phase_margin_deg",
        "power_mw",
        "fc_hz",
        "center_hz",
        "q_factor",
        "iout_a",
        "vref_v",
        "line_regulation_mv_per_v",
        "compliance_voltage_v",
        "oscillation_hz",
        "decision_delay_s",
        "output_swing_v",
        "common_mode_final_v",
        "max_slew_v_per_us",
        "onoise_total_vrms",
        "inoise_total_arms",
    ):
        value = _first_metric_value(per_analysis, key)
        if value is not None:
            flat_metrics[key] = value

    return {
        "topology": topology,
        "per_analysis": per_analysis,
        "flat_metrics": flat_metrics,
    }


def build_structured_verification(
    topology,
    plan,
    constraints,
    sizing,
    sim,
    legacy_summary,
    analysis_metrics,
    log_text="",
):
    spec_checks = _build_spec_checks(
        topology=topology,
        constraints=constraints,
        sim=sim,
        legacy_summary=legacy_summary,
        analysis_metrics=analysis_metrics,
    )
    requirement_evaluations = _build_requirement_evaluations(
        topology=topology,
        constraints=constraints,
        analysis_metrics=analysis_metrics,
        spec_checks=spec_checks,
    )
    failure_taxonomy = _build_failure_taxonomy(
        topology=topology,
        constraints=constraints,
        sim=sim,
        legacy_summary=legacy_summary,
        analysis_metrics=analysis_metrics,
        spec_checks=spec_checks,
        requirement_evaluations=requirement_evaluations,
        log_text=log_text,
    )
    overall_verdict = _overall_verdict(requirement_evaluations)

    summary = dict(legacy_summary or {})
    summary["simulation_plan"] = plan
    summary["analysis_results"] = analysis_metrics["per_analysis"]
    summary["extracted_metrics"] = analysis_metrics["flat_metrics"]
    summary["spec_checks"] = spec_checks
    summary["requirement_evaluations"] = requirement_evaluations
    summary["failure_taxonomy"] = failure_taxonomy
    summary["active_failure_categories"] = [item["category"] for item in failure_taxonomy["active_failures"]]
    summary["spec_passes"] = sum(1 for item in requirement_evaluations if item.get("status") == "pass")
    summary["spec_fails"] = sum(1 for item in requirement_evaluations if item.get("status") == "fail")
    summary["spec_unknown"] = sum(1 for item in requirement_evaluations if item.get("status") == "unknown")
    summary["overall_verdict"] = overall_verdict
    if summary["spec_fails"] > 0 or summary["active_failure_categories"]:
        summary["final_status"] = "fail"
    elif overall_verdict == "fully_verified":
        summary["final_status"] = "pass"
    else:
        summary["final_status"] = "partial"
    summary["overall_pass"] = (
        bool(summary.get("overall_pass", True))
        and summary["final_status"] == "pass"
        and overall_verdict == "fully_verified"
    )
    return summary


def build_final_status_summary(topology, plan, sim, verification_summary):
    return {
        "topology": topology,
        "status": verification_summary.get("final_status", "fail"),
        "overall_verdict": verification_summary.get("overall_verdict"),
        "overall_pass": bool(verification_summary.get("overall_pass")),
        "planned_analyses": list(plan.get("analyses") or []),
        "executed_analyses": [
            name
            for name, payload in (verification_summary.get("analysis_results") or {}).items()
            if payload.get("executed")
        ],
        "active_failure_categories": list(verification_summary.get("active_failure_categories") or []),
        "artifact_dir": sim.get("artifact_dir"),
    }


def write_artifact_bundle(base_dir, sim, analysis_metrics, verification_summary, final_status_summary):
    directories = {
        "netlist": os.path.join(base_dir, "netlist"),
        "logs": os.path.join(base_dir, "logs"),
        "plots": os.path.join(base_dir, "plots"),
        "data": os.path.join(base_dir, "data"),
        "reports": os.path.join(base_dir, "reports"),
    }
    for path in directories.values():
        os.makedirs(path, exist_ok=True)

    manifest = {
        "netlist": [],
        "logs": [],
        "plots": [],
        "data": [],
        "reports": [],
    }

    for key, bucket in (
        ("saved_netlist_path", "netlist"),
        ("log_path", "logs"),
        ("ac_plot", "plots"),
        ("dc_plot", "plots"),
        ("tran_plot", "plots"),
        ("ac_csv", "data"),
        ("ac_phase_csv", "data"),
        ("dc_csv", "data"),
        ("tran_in_csv", "data"),
        ("tran_out_csv", "data"),
        ("tran_outn_csv", "data"),
        ("tran_diff_csv", "data"),
        ("tran_qb_csv", "data"),
    ):
        copied = _copy_if_present(sim.get(key), directories[bucket])
        if copied:
            manifest[bucket].append(copied)

    for key, filename in (("stdout", "stdout.txt"), ("stderr", "stderr.txt")):
        value = sim.get(key)
        if value is None:
            continue
        path = os.path.join(directories["logs"], filename)
        with open(path, "w") as handle:
            handle.write(value or "")
        manifest["logs"].append(path)

    report_payloads = {
        "extracted_metrics.json": analysis_metrics,
        "verification_report.json": verification_summary,
        "final_status_summary.json": final_status_summary,
        "simulation_result.json": sim,
    }
    for filename, payload in report_payloads.items():
        path = os.path.join(directories["reports"], filename)
        with open(path, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        manifest["reports"].append(path)

    summary_txt = os.path.join(directories["reports"], "final_status_summary.txt")
    with open(summary_txt, "w") as handle:
        handle.write(_render_summary_text(final_status_summary))
    manifest["reports"].append(summary_txt)

    manifest_path = os.path.join(directories["reports"], "artifact_manifest.json")
    with open(manifest_path, "w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    manifest["reports"].append(manifest_path)
    return manifest


def _analysis_enabled(plan, name):
    return name in set(plan.get("analyses") or [])


def _execution_kind(planned, executed):
    if planned and executed:
        return "planned_simulation"
    if executed and not planned:
        return "precheck_only"
    return "not_run"


def _artifact_refs(sim, keys):
    refs = []
    for key in keys:
        value = sim.get(key)
        if value:
            refs.append(value)
    return refs


def _upsert_check(checks, payload):
    name = payload.get("name")
    for index, item in enumerate(checks):
        if item.get("name") == name:
            checks[index] = payload
            return
    checks.append(payload)


def _first_metric_value(analysis_metrics, metric_name):
    for payload in analysis_metrics.values():
        value = (payload.get("metrics") or {}).get(metric_name)
        if value is not None:
            return value
    return None


def _build_spec_checks(topology, constraints, sim, legacy_summary, analysis_metrics):
    checks = []
    seen = set()

    for item in list((legacy_summary or {}).get("target_checks") or []):
        name = item.get("name")
        if not name or name in seen:
            continue
        checks.append(
            {
                "name": name,
                "measured": item.get("measured"),
                "target": item.get("target"),
                "status": item.get("status", "unknown"),
                "source": "legacy_target_check",
            }
        )
        seen.add(name)

    ac_metrics = ((analysis_metrics.get("per_analysis") or {}).get("ac") or {}).get("metrics") or {}
    dc_metrics = ((analysis_metrics.get("per_analysis") or {}).get("dc") or {}).get("metrics") or {}
    tran_metrics = ((analysis_metrics.get("per_analysis") or {}).get("tran") or {}).get("metrics") or {}
    op_metrics = ((analysis_metrics.get("per_analysis") or {}).get("op") or {}).get("metrics") or {}

    if constraints.get("phase_margin_deg") is not None:
        measured = ac_metrics.get("phase_margin_deg")
        target = float(constraints.get("phase_margin_deg"))
        _upsert_check(
            checks,
            {
                "name": "phase_margin_deg",
                "measured": measured,
                "target": target,
                "status": _min_check(measured, target),
                "source": "stability_extractor",
            },
        )
        seen.add("phase_margin_deg")

    if constraints.get("target_gain_db") is not None and topology == "transimpedance_frontend":
        measured = ac_metrics.get("gain_db")
        target = float(constraints.get("target_gain_db"))
        _upsert_check(
            checks,
            {
                "name": "gain_db",
                "measured": measured,
                "target": target,
                "status": _target_check(measured, target, rel_tol=0.20, abs_tol=3.0),
                "source": "transimpedance_extractor",
            },
        )
        seen.add("gain_db")

    if constraints.get("target_transimpedance_ohm") is not None:
        measured_db = ac_metrics.get("gain_db")
        measured = None if measured_db is None else 10.0 ** (float(measured_db) / 20.0)
        target = float(constraints.get("target_transimpedance_ohm"))
        _upsert_check(
            checks,
            {
                "name": "transimpedance_ohm",
                "measured": measured,
                "target": target,
                "status": _target_check(measured, target, rel_tol=0.20, abs_tol=0.0),
                "source": "transimpedance_extractor",
            },
        )
        seen.add("transimpedance_ohm")

    if constraints.get("target_gm_s") is not None:
        measured = None
        if op_metrics.get("devices"):
            for values in (op_metrics.get("devices") or {}).values():
                if values.get("gm_s") is not None:
                    measured = values.get("gm_s")
                    break
        _upsert_check(
            checks,
            {
                "name": "gm_s",
                "measured": measured,
                "target": float(constraints.get("target_gm_s")),
                "status": _target_check(measured, float(constraints.get("target_gm_s")), rel_tol=0.25, abs_tol=0.0),
                "source": "op_extractor",
            },
        )
        seen.add("gm_s")

    if constraints.get("target_vout_q_v") is not None:
        measured = tran_metrics.get("out_final_v") or tran_metrics.get("common_mode_final_v")
        target = float(constraints.get("target_vout_q_v"))
        tolerance = max(0.05, 0.10 * max(abs(target), 1e-9))
        status = "unknown" if measured is None else ("pass" if abs(float(measured) - target) <= tolerance else "fail")
        _upsert_check(
            checks,
            {
                "name": "output_quiescent_v",
                "measured": measured,
                "target": target,
                "status": status,
                "source": "transient_extractor",
            },
        )
        seen.add("output_quiescent_v")

    if constraints.get("target_bw_hz") is not None:
        measured = ac_metrics.get("bandwidth_hz")
        target = float(constraints.get("target_bw_hz"))
        _upsert_check(
            checks,
            {
                "name": "bandwidth_hz",
                "measured": measured,
                "target": target,
                "status": _min_check(measured, target),
                "source": "ac_extractor",
            },
        )
        seen.add("bandwidth_hz")

    if constraints.get("power_limit_mw") is not None:
        measured = sim.get("power_mw") or op_metrics.get("estimated_power_mw")
        target = float(constraints.get("power_limit_mw"))
        status = "unknown" if measured is None else ("pass" if float(measured) <= target else "fail")
        _upsert_check(
            checks,
            {
                "name": "power_mw",
                "measured": measured,
                "target": target,
                "status": status,
                "source": "op_extractor",
            },
        )
        seen.add("power_mw")

    output_swing_target = constraints.get("target_output_swing_v")
    if output_swing_target is None:
        output_swing_target = constraints.get("min_output_swing_v")
    if output_swing_target is not None:
        measured = tran_metrics.get("output_swing_v") or dc_metrics.get("output_swing_v")
        target = float(output_swing_target)
        _upsert_check(
            checks,
            {
                "name": "output_swing_v",
                "measured": measured,
                "target": target,
                "status": _min_check(measured, target),
                "source": "swing_extractor",
            },
        )
        seen.add("output_swing_v")

    common_mode_target = constraints.get("target_vout_q_v")
    if common_mode_target is not None:
        measured = tran_metrics.get("common_mode_final_v") or tran_metrics.get("out_final_v")
        tolerance = max(0.05, 0.10 * max(abs(float(common_mode_target)), 1e-9))
        status = "unknown"
        if measured is not None:
            status = "pass" if abs(float(measured) - float(common_mode_target)) <= tolerance else "fail"
        _upsert_check(
            checks,
            {
                "name": "common_mode_final_v",
                "measured": measured,
                "target": common_mode_target,
                "status": status,
                "source": "common_mode_extractor",
            },
        )
        seen.add("common_mode_final_v")

    if constraints.get("target_slew_v_per_us") is not None:
        measured = tran_metrics.get("max_slew_v_per_us")
        target = float(constraints.get("target_slew_v_per_us"))
        _upsert_check(
            checks,
            {
                "name": "max_slew_v_per_us",
                "measured": measured,
                "target": target,
                "status": _min_check(measured, target),
                "source": "transient_extractor",
            },
        )
        seen.add("max_slew_v_per_us")

    if constraints.get("target_vref_v") is not None:
        measured = dc_metrics.get("vref_v") or sim.get("vref_v")
        target = float(constraints.get("target_vref_v"))
        _upsert_check(
            checks,
            {
                "name": "vref_v",
                "measured": measured,
                "target": target,
                "status": _target_check(measured, target, rel_tol=0.08, abs_tol=0.06),
                "source": "dc_extractor",
            },
        )
        seen.add("vref_v")

    if constraints.get("target_line_regulation_mv_per_v") is not None:
        measured = abs(dc_metrics.get("line_regulation_mv_per_v")) if dc_metrics.get("line_regulation_mv_per_v") is not None else None
        target = float(constraints.get("target_line_regulation_mv_per_v"))
        status = "unknown" if measured is None else ("pass" if float(measured) <= target else "fail")
        _upsert_check(
            checks,
            {
                "name": "line_regulation_mv_per_v",
                "measured": measured,
                "target": target,
                "status": status,
                "source": "dc_extractor",
            },
        )
        seen.add("line_regulation_mv_per_v")

    if constraints.get("target_onoise_total_vrms") is not None:
        noise_metrics = ((analysis_metrics.get("per_analysis") or {}).get("noise") or {}).get("metrics") or {}
        measured = noise_metrics.get("onoise_total_vrms")
        target = float(constraints.get("target_onoise_total_vrms"))
        status = "unknown" if measured is None else ("pass" if float(measured) <= target else "fail")
        _upsert_check(
            checks,
            {
                "name": "onoise_total_vrms",
                "measured": measured,
                "target": target,
                "status": status,
                "source": "noise_extractor",
            },
        )
        seen.add("onoise_total_vrms")

    if constraints.get("target_iout_a") is not None:
        measured = dc_metrics.get("iout_a") or sim.get("iout_a")
        target = float(constraints.get("target_iout_a"))
        _upsert_check(
            checks,
            {
                "name": "iout_a",
                "measured": measured,
                "target": target,
                "status": _target_check(measured, target, rel_tol=0.10, abs_tol=0.0),
                "source": "dc_extractor",
            },
        )
        seen.add("iout_a")

    if constraints.get("compliance_v") is not None:
        measured = dc_metrics.get("compliance_voltage_v")
        target = float(constraints.get("compliance_v"))
        status = "unknown" if measured is None else ("pass" if float(measured) <= target else "fail")
        _upsert_check(
            checks,
            {
                "name": "compliance_voltage_v",
                "measured": measured,
                "target": target,
                "status": status,
                "source": "dc_extractor",
            },
        )
        seen.add("compliance_voltage_v")

    if constraints.get("target_decision_delay_s") is not None:
        measured = tran_metrics.get("decision_delay_s") or sim.get("decision_delay_s")
        target = float(constraints.get("target_decision_delay_s"))
        status = "unknown" if measured is None else ("pass" if float(measured) <= target else "fail")
        _upsert_check(
            checks,
            {
                "name": "decision_delay_s",
                "measured": measured,
                "target": target,
                "status": status,
                "source": "transient_extractor",
            },
        )
        seen.add("decision_delay_s")

    if topology in {"comparator", "static_comparator", "latched_comparator"}:
        measured = sim.get("decision_correct")
        _upsert_check(
            checks,
            {
                "name": "decision_correct",
                "measured": measured,
                "target": True,
                "status": "pass" if measured is True else ("fail" if measured is False else "unknown"),
                "source": "transient_extractor",
            },
        )
        seen.add("decision_correct")

    if topology == "sram6t_cell":
        measured = sim.get("write_ok")
        _upsert_check(
            checks,
            {
                "name": "write_ok",
                "measured": measured,
                "target": True,
                "status": "pass" if measured is True else ("fail" if measured is False else "unknown"),
                "source": "transient_extractor",
            },
        )
        seen.add("write_ok")

    if topology == "lc_oscillator_cross_coupled" and "startup_ok" not in seen:
        startup_ok = sim.get("oscillation_hz") is not None
        checks.append(
            {
                "name": "startup_ok",
                "measured": startup_ok if sim.get("oscillation_hz") is not None else False,
                "target": True,
                "status": "pass" if startup_ok else "fail",
                "source": "startup_extractor",
            }
        )

    return checks


def _build_requirement_evaluations(topology, constraints, analysis_metrics, spec_checks):
    evaluations = []
    seen = set()

    for check in spec_checks:
        name = check.get("name")
        if not name or name in seen or name.startswith("reference::"):
            continue
        if name not in REQUIREMENT_NAMES:
            continue
        assessment = _assessment_from_check(check)
        evaluations.append(
            {
                "requirement": name,
                "requested": check.get("target"),
                "measured": check.get("measured"),
                "status": check.get("status", "unknown"),
                "assessment": assessment,
                "evidence": check.get("source", "simulation"),
            }
        )
        seen.add(name)
    return evaluations


def _assessment_from_check(check):
    if str(check.get("source", "")).startswith("reference"):
        return "analytically_estimated_only"
    if check.get("status") == "fail":
        return "simulated_but_failed"
    if check.get("status") == "pass":
        return "fully_verified"
    return "not_tested"


def _overall_verdict(requirement_evaluations):
    if not requirement_evaluations:
        return "not_tested"
    assessments = {item.get("assessment") for item in requirement_evaluations}
    if "simulated_but_failed" in assessments:
        return "failed"
    if "not_tested" in assessments:
        return "partially_verified"
    if "analytically_estimated_only" in assessments:
        return "analytically_estimated_only"
    return "fully_verified"


def _build_failure_taxonomy(
    topology,
    constraints,
    sim,
    legacy_summary,
    analysis_metrics,
    spec_checks,
    requirement_evaluations,
    log_text,
):
    failures = []
    check_map = {item.get("name"): item for item in spec_checks}
    op_metrics = ((analysis_metrics.get("per_analysis") or {}).get("op") or {}).get("metrics") or {}
    tran_metrics = ((analysis_metrics.get("per_analysis") or {}).get("tran") or {}).get("metrics") or {}
    ac_metrics = ((analysis_metrics.get("per_analysis") or {}).get("ac") or {}).get("metrics") or {}
    stage_report = sim.get("netlist_stage_report") or {}
    active_check_names = {
        item.get("requirement")
        for item in (requirement_evaluations or [])
        if item.get("status") == "fail"
    }

    if stage_report and not stage_report.get("valid", True):
        failures.append(
            {
                "category": "topology_mismatch",
                "summary": stage_report.get("error") or "Composite topology realization did not match the planned structure.",
            }
        )

    near_triode = op_metrics.get("near_triode_devices") or []
    if near_triode or op_metrics.get("bias_ok") is False:
        failures.append(
            {
                "category": "bad_bias_point",
                "summary": "Operating-point characterization indicates weak saturation margin.",
                "devices": near_triode,
            }
        )

    if any(name in active_check_names for name in {"gain_db", "transimpedance_ohm"}):
        failures.append(
            {
                "category": "gain_miss",
                "summary": "Measured small-signal gain did not satisfy the requested target.",
            }
        )

    if any(name in active_check_names for name in {"bandwidth_hz", "ugbw_hz", "cutoff_hz", "center_hz"}):
        failures.append(
            {
                "category": "bandwidth_miss",
                "summary": "Measured frequency-response target missed the requested bandwidth or UGBW goal.",
            }
        )

    phase_check = check_map.get("phase_margin_deg")
    overshoot = tran_metrics.get("overshoot_pct")
    if (
        (phase_check and phase_check.get("status") == "fail")
        or (
            constraints.get("phase_margin_deg") is not None
            and ac_metrics.get("phase_margin_deg") is None
            and overshoot is not None
            and float(overshoot) > 30.0
        )
    ):
        failures.append(
            {
                "category": "unstable_or_poor_phase_margin",
                "summary": "Stability margin is below target or transient peaking suggests poor phase margin.",
            }
        )

    if "power_mw" in active_check_names:
        failures.append(
            {
                "category": "power_too_high",
                "summary": "Quiescent power exceeds the specified power budget.",
            }
        )

    if "output_swing_v" in active_check_names:
        failures.append(
            {
                "category": "output_swing_violation",
                "summary": "Measured output swing is smaller than the requested target.",
            }
        )

    if "common_mode_final_v" in active_check_names:
        failures.append(
            {
                "category": "common_mode_violation",
                "summary": "The observed output common-mode operating point missed the requested target.",
            }
        )

    if topology == "lc_oscillator_cross_coupled" and sim.get("oscillation_hz") is None:
        failures.append(
            {
                "category": "startup_failure",
                "summary": "Oscillation did not build up in transient, indicating startup failure.",
            }
        )

    if _looks_like_convergence_failure(sim=sim, log_text=log_text, legacy_summary=legacy_summary):
        failures.append(
            {
                "category": "convergence_failure",
                "summary": "The simulator reported a numerical convergence or execution failure.",
            }
        )

    ordered = []
    seen = set()
    for category in FAILURE_CATEGORY_ORDER:
        for item in failures:
            if item["category"] == category and category not in seen:
                ordered.append(item)
                seen.add(category)
    return {
        "supported_categories": list(FAILURE_CATEGORY_ORDER),
        "active_failures": ordered,
    }


def _looks_like_convergence_failure(sim, log_text, legacy_summary):
    text = str(log_text or "").lower()
    keywords = (
        "convergence",
        "timestep too small",
        "singular matrix",
        "aborted",
        "no such vector",
        "failed",
        "error",
    )
    if sim.get("returncode") not in (None, 0):
        return True
    if any(keyword in text for keyword in keywords):
        return True
    if (legacy_summary or {}).get("target_checks"):
        for item in (legacy_summary or {}).get("target_checks") or []:
            if item.get("name") == "simulation_executed" and item.get("status") == "fail":
                return True
    return False


def _min_check(measured, target):
    if measured is None or target is None:
        return "unknown"
    return "pass" if float(measured) >= float(target) else "fail"


def _target_check(measured, target, rel_tol=0.15, abs_tol=0.0):
    if measured is None or target is None:
        return "unknown"
    measured = float(measured)
    target = float(target)
    err = abs(measured - target)
    rel_err = err / max(abs(target), 1e-30)
    if abs_tol is not None and err <= float(abs_tol):
        return "pass"
    return "pass" if rel_err <= float(rel_tol) else "fail"


def _copy_if_present(source, target_dir):
    if not source or not os.path.exists(source):
        return None
    destination = os.path.join(target_dir, os.path.basename(source))
    if os.path.abspath(source) != os.path.abspath(destination):
        shutil.copy2(source, destination)
    return destination


def _render_summary_text(final_status_summary):
    lines = [
        f"status: {final_status_summary.get('status')}",
        f"overall_verdict: {final_status_summary.get('overall_verdict')}",
        f"topology: {final_status_summary.get('topology')}",
        "planned_analyses: " + ", ".join(final_status_summary.get("planned_analyses") or []),
        "executed_analyses: " + ", ".join(final_status_summary.get("executed_analyses") or []),
        "active_failure_categories: " + ", ".join(final_status_summary.get("active_failure_categories") or []),
        f"artifact_dir: {final_status_summary.get('artifact_dir')}",
    ]
    return "\n".join(lines) + "\n"
