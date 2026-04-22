import argparse
import os
import json
import shutil
from datetime import datetime

from agents.design_status import DesignStatus
from core.demo_catalog import get_demo_case, get_demo_profile, list_demo_cases, list_demo_profiles
from core.demo_safe import (
    DEMO_SAFE_CASES,
    extract_specs,
    pass_fail_reasons,
    summarize_netlist,
    summarize_sizing,
)
from core.final_showcase import (
    FINAL_SHOWCASE_BACKUP_COMMAND,
    FINAL_SHOWCASE_CASES,
    FINAL_SHOWCASE_CASE_DETAILS,
    FINAL_SHOWCASE_PRIMARY_COMMAND,
    build_showcase_case_summary,
    dumps_pretty,
    render_showcase_case_markdown,
    render_showcase_rollup_markdown,
    stable_summary_index,
)
from core.preflight_checks import format_preflight_report, run_preflight_checks
from core.reference_knowledge import load_reference_catalog, resolve_reference_paths
from core.runtime_backend import resolve_llm_backend
from core.shared_memory import SharedMemory

from agents.topology_agent import TopologyAgent
from agents.sizing_agent import SizingAgent
from agents.constraints_agent import ConstraintAgent
from agents.netlist_agent import NetlistAgent
from agents.op_point_agent import OpPointAgent
from agents.simulation_agent import SimulationAgent
from agents.refinement_agent import RefinementAgent
from agents.orchestration_agent import OrchestrationAgent


def build_llm():
    resolution = resolve_llm_backend(instantiate=True)
    print(f"[LLM] {resolution.message}")
    return resolution

def _fmt_value(value, unit=""):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}{unit}"
    return f"{value}{unit}"


def _banner_for_state(final_state: dict) -> str:
    status = final_state.get("status")
    constraints_report = final_state.get("constraints_report") or {}
    sim = final_state.get("simulation_results") or {}

    if status == DesignStatus.DESIGN_VALIDATED:
        if constraints_report.get("warnings") or sim.get("parser_warning"):
            return "[VALIDATED WITH WARNINGS]"
        return "[VALIDATED]"
    if status in {
        DesignStatus.ORCHESTRATION_FAILED,
        DesignStatus.DESIGN_INVALID,
        DesignStatus.DESIGN_INVALID_AFTER_RETRIES,
        DesignStatus.SIMULATION_FAILED,
        DesignStatus.NETLIST_FAILED,
        DesignStatus.CONSTRAINTS_FAILED,
        DesignStatus.SIZING_FAILED,
        DesignStatus.TOPOLOGY_FAILED,
    }:
        return "[FAILED]"
    return "[IN PROGRESS]"


def _format_metrics_block(sim: dict):
    rows = []
    for label, key, unit in (
        ("Gain", "gain_db", " dB"),
        ("PeakGain", "peak_gain_db", " dB"),
        ("BW", "bandwidth_hz", " Hz"),
        ("UGBW", "ugbw_hz", " Hz"),
        ("Cutoff", "fc_hz", " Hz"),
        ("Center", "center_hz", " Hz"),
        ("Q", "q_factor", ""),
        ("Damping", "damping_ratio", ""),
        ("Rolloff", "rolloff_db_per_dec", " dB/dec"),
        ("Power", "power_mw", " mW"),
        ("Pmargin", "power_margin_mw", " mW"),
        ("Iout", "iout_a", " A"),
        ("Vref", "vref_v", " V"),
        ("Fosc", "oscillation_hz", " Hz"),
        ("Delay", "decision_delay_s", " s"),
        ("TGain", "transient_gain_db", " dB"),
        ("Qfinal", "q_final_v", " V"),
        ("QBfinal", "qb_final_v", " V"),
        ("Vhigh", "logic_high_v", " V"),
        ("Vlow", "logic_low_v", " V"),
    ):
        if sim.get(key) is not None:
            rows.append(f"  {label:<8} {_fmt_value(sim.get(key), unit)}")
    if sim.get("write_ok") is not None:
        rows.append(f"  {'SRAM':<8} {'WRITE_OK' if sim.get('write_ok') else 'WRITE_FAIL'}")
    if sim.get("power_limit_ok") is not None:
        rows.append(f"  {'Plimit':<8} {'PASS' if sim.get('power_limit_ok') else 'FAIL'}")
    return rows


def _format_history_tail(final_state: dict, count: int = 10):
    history = (final_state.get("history") or [])[-count:]
    lines = ["Recent history:"]
    for item in history:
        event = item.get("event")
        data = item.get("data")
        ts = item.get("timestamp", "")
        if isinstance(data, dict):
            if event == "write":
                summary = ", ".join(sorted(data.keys()))
            elif event == "agent_executed":
                summary = f"{data.get('agent')} -> {data.get('status')}"
            else:
                summary = ", ".join(f"{k}={v}" for k, v in list(data.items())[:3])
        else:
            summary = str(data)
        lines.append(f"  - {ts} | {event} | {summary}")
    return lines


def _format_key_value_block(title: str, payload: dict, allowed_keys=None):
    payload = dict(payload or {})
    lines = [title]
    keys = list(allowed_keys or payload.keys())
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        lines.append(f"  - {key}: {_fmt_value(value)}")
    if len(lines) == 1:
        lines.append("  - n/a")
    return lines


def _format_list_block(title: str, items):
    lines = [title]
    for item in items or []:
        lines.append(f"  - {item}")
    if len(lines) == 1:
        lines.append("  - n/a")
    return lines


def _format_analysis_block(verification: dict):
    lines = ["Simulation Analyses Actually Run:"]
    analysis_results = verification.get("analysis_results") or {}
    for name in ("op", "dc", "ac", "tran", "noise"):
        payload = analysis_results.get(name) or {}
        if not payload:
            continue
        planned = "yes" if payload.get("planned") else "no"
        executed = "yes" if payload.get("executed") else "no"
        execution_kind = payload.get("execution_kind", "not_run")
        metric_keys = sorted((payload.get("metrics") or {}).keys())
        lines.append(
            f"  - {name}: planned={planned}, executed={executed}, mode={execution_kind}, "
            f"metrics={', '.join(metric_keys[:8]) if metric_keys else 'none'}"
        )
    if len(lines) == 1:
        lines.append("  - n/a")
    return lines


def _format_requirement_block(verification: dict):
    lines = ["Requirement Status:"]
    evaluations = verification.get("requirement_evaluations") or []
    if not evaluations:
        lines.append("  - No explicit requirement evaluations were generated.")
        return lines
    for item in evaluations:
        lines.append(
            "  - "
            f"{item.get('requirement')}: requested={_fmt_value(item.get('requested'))}, "
            f"measured={_fmt_value(item.get('measured'))}, "
            f"status={item.get('status')}, assessment={item.get('assessment')}"
        )
    return lines


def _format_failure_block(verification: dict):
    lines = ["Failure Reasons:"]
    failures = ((verification.get("failure_taxonomy") or {}).get("active_failures") or [])
    if not failures:
        lines.append("  - none")
        return lines
    for item in failures:
        lines.append(f"  - {item.get('category')}: {item.get('summary')}")
    return lines


def _format_artifact_block(sim: dict):
    lines = ["Artifact File Paths:"]
    manifest = sim.get("artifact_manifest") or {}
    if manifest:
        for bucket in ("netlist", "logs", "plots", "data", "reports"):
            paths = manifest.get(bucket) or []
            for path in paths:
                lines.append(f"  - {bucket}: {path}")
    else:
        for key in (
            "saved_netlist_path",
            "log_path",
            "ac_plot",
            "dc_plot",
            "tran_plot",
            "ac_csv",
            "ac_phase_csv",
            "dc_csv",
            "tran_in_csv",
            "tran_out_csv",
            "tran_outn_csv",
            "tran_diff_csv",
        ):
            if sim.get(key):
                lines.append(f"  - {key}: {sim.get(key)}")
    if len(lines) == 1:
        lines.append("  - n/a")
    return lines


def format_final_report(case_name: str, final_state: dict) -> str:
    sim = final_state.get("simulation_results") or {}
    constraints_report = final_state.get("constraints_report") or {}
    case_meta = final_state.get("case_metadata") or {}
    verification = sim.get("verification_summary") or final_state.get("verification_summary") or {}
    final_status_summary = sim.get("final_status_summary") or {}
    sizing = final_state.get("sizing") or {}
    constraints = final_state.get("constraints") or {}
    extracted_metrics = verification.get("extracted_metrics") or {}
    selected_topologies = final_state.get("selected_topologies") or [final_state.get("selected_topology") or "n/a"]

    lines = [
        "",
        _banner_for_state(final_state),
        "=== Final Verification Report ===",
        f"Case name: {case_name}",
        f"Display name: {case_meta.get('display_name', 'n/a')}",
        f"Requested specification: {final_state.get('specification', 'n/a')}",
        f"Selected topology: {final_state.get('selected_topology')}",
        f"Selected stage topologies: {', '.join(selected_topologies)}",
        f"Framework status: {final_state.get('status')}",
        f"Overall verdict: {verification.get('overall_verdict', 'unknown')}",
        f"Verification status: {verification.get('final_status', 'unknown')}",
        f"Fully verified: {verification.get('overall_pass')}",
        f"Iterations completed: {final_state.get('iteration', 0)}",
        f"Netlist source: {final_state.get('netlist_source', 'n/a')}",
    ]
    llm_resolution = final_state.get("llm_resolution") or {}
    if llm_resolution:
        lines.append(
            "LLM backend: "
            f"configured={llm_resolution.get('configured_backend')} "
            f"resolved={llm_resolution.get('resolved_backend')} "
            f"fallback={llm_resolution.get('fallback_used')}"
        )
    reference_catalog = final_state.get("reference_catalog_summary") or {}
    if reference_catalog:
        lines.append(
            "Reference catalog: "
            f"{reference_catalog.get('entry_count', 0)} entries from "
            f"{', '.join(reference_catalog.get('roots') or [])}"
        )
    for label, key in (
        ("Topology references", "topology_reference_summary"),
        ("Sizing references", "sizing_reference_summary"),
        ("Netlist references", "netlist_reference_summary"),
        ("Verification references", "verification_reference_summary"),
    ):
        summary = final_state.get(key) or {}
        hits = summary.get("used") or summary.get("hits") or []
        if hits:
            lines.append(f"{label}: " + ", ".join(item.get("id") or item.get("title", "unknown") for item in hits[:4]))

    topology_plan = final_state.get("topology_plan") or {}
    if topology_plan.get("mode"):
        lines.append(f"Topology plan mode: {topology_plan.get('mode')} ({topology_plan.get('source', 'unknown')})")
    stage_report = final_state.get("netlist_stage_report") or sim.get("netlist_stage_report") or {}
    if stage_report:
        lines.append(
            "Stage realization: "
            f"count_match={stage_report.get('stage_count_match')} "
            f"order_match={stage_report.get('topology_order_match')}"
        )

    lines.extend(_format_key_value_block("Requested Constraints:", constraints))
    lines.extend(_format_list_block("Sizing Summary:", summarize_sizing(sizing)))
    lines.extend(_format_analysis_block(verification))
    lines.extend(_format_key_value_block("Extracted Metrics:", extracted_metrics))
    lines.extend(_format_requirement_block(verification))
    lines.extend(
        [
            "Verification Coverage:",
            f"  - spec_passes: {verification.get('spec_passes', 0)}",
            f"  - spec_fails: {verification.get('spec_fails', 0)}",
            f"  - spec_unknown: {verification.get('spec_unknown', 0)}",
            f"  - legacy_check_coverage: {_fmt_value(verification.get('coverage_ratio'))}",
        ]
    )
    lines.extend(_format_failure_block(verification))

    artifact_dir = sim.get("artifact_dir")
    if artifact_dir:
        lines.append(f"Latest artifact dir: {artifact_dir}")
    if sim.get("simulation_skipped"):
        lines.append(f"Simulation status: skipped ({sim.get('skip_reason', 'reason not provided')})")
    if sim.get("saved_netlist_path"):
        lines.append(f"Simulated netlist: {sim.get('saved_netlist_path')}")
        lines.append("Simulation provenance: metrics and plots below are derived from this artifact netlist.")
    lines.extend(_format_artifact_block(sim))

    if constraints_report.get("warnings"):
        lines.append("Constraint warnings:")
        lines.extend(f"  - {warning}" for warning in constraints_report["warnings"])

    error_fields = [
        ("Topology error", final_state.get("topology_error")),
        ("Sizing error", final_state.get("sizing_error")),
        ("Constraint issues", constraints_report.get("issues")),
        ("Netlist error", final_state.get("netlist_error")),
        ("Simulation error", final_state.get("simulation_error")),
        ("Simulation skipped", sim.get("skip_reason")),
        ("Parser warning", sim.get("parser_warning")),
    ]
    for label, value in error_fields:
        if value:
            if isinstance(value, list):
                lines.append(f"{label}: " + "; ".join(str(item) for item in value))
            else:
                lines.append(f"{label}: {value}")

    if not verification.get("overall_pass"):
        lines.append(
            "Sponsor review note: "
            "this case is not fully verified unless every requirement above is marked "
            "`assessment=fully_verified` and the overall verdict is `fully_verified`."
        )

    if os.getenv("SHOW_HISTORY", "0").strip() == "1":
        lines.extend(_format_history_tail(final_state))

    return "\n".join(lines)


def _artifact_summary(case_name: str, final_state: dict) -> dict:
    sim = final_state.get("simulation_results") or {}
    constraints = final_state.get("constraints") or {}
    case_meta = final_state.get("case_metadata") or {}
    verification = sim.get("verification_summary") or {}
    return {
        "case": case_name,
        "display_name": case_meta.get("display_name"),
        "specification": final_state.get("specification"),
        "topology": final_state.get("selected_topology"),
        "selected_topologies": final_state.get("selected_topologies"),
        "topology_plan": final_state.get("topology_plan"),
        "status": final_state.get("status"),
        "overall_verdict": verification.get("overall_verdict"),
        "llm_resolution": final_state.get("llm_resolution"),
        "simulation_intent": (case_meta.get("simulation_plan") or {}).get("intent"),
        "analyses": sim.get("analyses") or (case_meta.get("simulation_plan") or {}).get("analyses", []),
        "requested_constraints": constraints,
        "sizing": final_state.get("sizing"),
        "targets": constraints,
        "measured": verification.get("extracted_metrics") or {
            "gain_db": sim.get("gain_db"),
            "bandwidth_hz": sim.get("bandwidth_hz"),
            "ugbw_hz": sim.get("ugbw_hz"),
            "cutoff_hz": sim.get("fc_hz"),
            "center_hz": sim.get("center_hz"),
            "power_mw": sim.get("power_mw"),
            "power_margin_mw": sim.get("power_margin_mw"),
            "oscillation_hz": sim.get("oscillation_hz"),
            "decision_delay_s": sim.get("decision_delay_s"),
        },
        "checks": {
            "power_limit_ok": sim.get("power_limit_ok"),
            "write_ok": sim.get("write_ok"),
            "decision_correct": sim.get("decision_correct"),
            "simulation_skipped": sim.get("simulation_skipped"),
            "skip_reason": sim.get("skip_reason"),
            "plot_validation_summary": sim.get("plot_validation_summary"),
            "composite_stage_report": sim.get("netlist_stage_report"),
        },
        "run_quality": {
            "iterations": final_state.get("iteration", 0),
            "first_pass_success": bool(
                final_state.get("status") == DesignStatus.DESIGN_VALIDATED
                and verification.get("overall_pass") is True
                and int(final_state.get("iteration", 0) or 0) == 0
            ),
        },
        "characterization": {
            "ac": sim.get("ac_characterization"),
            "transient": sim.get("transient_characterization"),
            "op": (final_state.get("op_point_results") or {}).get("characterization"),
        },
        "artifacts": {
            "saved_netlist_path": sim.get("saved_netlist_path"),
            "simulation_provenance": sim.get("simulation_provenance"),
            "ac_plot": sim.get("ac_plot"),
            "tran_plot": sim.get("tran_plot"),
            "dc_plot": sim.get("dc_plot"),
            "log_path": sim.get("log_path"),
        },
        "plot_validations": sim.get("plot_validations"),
        "verification_summary": sim.get("verification_summary"),
        "requirement_evaluations": verification.get("requirement_evaluations"),
        "artifact_manifest": sim.get("artifact_manifest"),
        "llm_calls": [
            item.get("data")
            for item in (final_state.get("history") or [])
            if item.get("event") == "llm_call"
        ],
    }


def _write_artifact_report(case_name: str, final_state: dict) -> None:
    sim = final_state.get("simulation_results") or {}
    artifact_dir = sim.get("artifact_dir")
    if not artifact_dir:
        return

    os.makedirs(artifact_dir, exist_ok=True)
    reports_dir = os.path.join(artifact_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_text = format_final_report(case_name, final_state) + "\n"
    with open(os.path.join(artifact_dir, "final_report.txt"), "w") as f:
        f.write(report_text)
    with open(os.path.join(reports_dir, "final_report.txt"), "w") as f:
        f.write(report_text)
    with open(os.path.join(artifact_dir, "metrics_summary.json"), "w") as f:
        json.dump(_artifact_summary(case_name, final_state), f, indent=2)
    with open(os.path.join(reports_dir, "metrics_summary.json"), "w") as f:
        json.dump(_artifact_summary(case_name, final_state), f, indent=2)


def _list_cases() -> None:
    print("Available DESIGN_CASE values:")
    for item in list_demo_cases():
        print(
            f"- {item['key']}: {item['display_name']} "
            f"(topology={item['forced_topology']}, model={item['demo_model']}, readiness={item['readiness']})"
        )


def _list_profiles() -> None:
    print("Available DEMO_PROFILE values:")
    for item in list_demo_profiles():
        print(f"- {item['name']}: {', '.join(item['cases'])}")


def run_preflight(profile_name: str = "ti_safe") -> dict:
    if profile_name:
        print(f"Preflight target profile hint: {profile_name}")
    report = run_preflight_checks()
    sanity = _run_profile_preflight_sanity(profile_name)
    report["profile_sanity"] = sanity
    if sanity.get("failures"):
        report["counts"]["FAIL"] = int(report["counts"].get("FAIL", 0)) + len(sanity["failures"])
        report["ok"] = False
    print(format_preflight_report(report))
    if sanity.get("cases"):
        print("Profile sanity (topology->sizing->constraints->netlist):")
        for item in sanity["cases"]:
            print(
                f"- {item['case']}: "
                f"topology={item['topology_ok']} sizing={item['sizing_ok']} "
                f"constraints={item['constraints_ok']} netlist={item['netlist_ok']}"
            )
    if sanity.get("failures"):
        print("Profile sanity failures: " + ", ".join(sanity["failures"]))
    return report


def _run_profile_preflight_sanity(profile_name: str) -> dict:
    if not profile_name:
        return {"cases": [], "failures": []}

    max_cases = max(1, int(os.getenv("PREFLIGHT_SANITY_CASES", "3")))
    try:
        case_names = get_demo_profile(profile_name)
    except Exception as exc:
        return {"cases": [], "failures": [f"Unknown profile '{profile_name}': {exc}"]}

    selected = list(case_names[:max_cases])
    rows = []
    failures = []
    reference_catalog = load_reference_catalog(resolve_reference_paths())
    for case_name in selected:
        try:
            case = get_demo_case(case_name)
            memory = SharedMemory()
            memory.write("specification", case["specification"])
            memory.write("constraints", case["constraints"])
            memory.write(
                "case_metadata",
                {
                    "case_key": case.get("case_key"),
                    "display_name": case.get("display_name"),
                    "forced_topology": case.get("forced_topology"),
                    "demo_model": case.get("demo_model", "native"),
                    "readiness": case.get("readiness", "stable"),
                    "artifact_label": case.get("artifact_label"),
                    "simulation_plan": case.get("simulation_plan", {}),
                },
            )

            topology_agent = TopologyAgent(llm=None, reference_catalog=reference_catalog)
            sizing_agent = SizingAgent(llm=None, reference_catalog=reference_catalog)
            constraint_agent = ConstraintAgent(reference_catalog=reference_catalog)
            netlist_agent = NetlistAgent(llm=None, reference_catalog=reference_catalog)

            topology_agent.run_agent(memory)
            topology_ok = memory.read("status") == DesignStatus.TOPOLOGY_SELECTED
            sizing_ok = False
            constraints_ok = False
            netlist_ok = False

            if topology_ok:
                sizing_agent.run_agent(memory)
                sizing_ok = memory.read("status") == DesignStatus.SIZING_COMPLETE
            if sizing_ok:
                constraint_agent.run_agent(memory)
                constraints_ok = memory.read("status") == DesignStatus.CONSTRAINTS_OK
            if constraints_ok:
                netlist_agent.run_agent(memory)
                netlist_ok = memory.read("status") == DesignStatus.NETLIST_GENERATED

            row = {
                "case": case_name,
                "topology_ok": topology_ok,
                "sizing_ok": sizing_ok,
                "constraints_ok": constraints_ok,
                "netlist_ok": netlist_ok,
            }
            rows.append(row)
            if not all((topology_ok, sizing_ok, constraints_ok, netlist_ok)):
                failures.append(case_name)
        except Exception:
            failures.append(case_name)
            rows.append(
                {
                    "case": case_name,
                    "topology_ok": False,
                    "sizing_ok": False,
                    "constraints_ok": False,
                    "netlist_ok": False,
                }
            )

    return {"cases": rows, "failures": failures}


def _print_demo_safe_case_summary(case_name: str, final_state: dict) -> None:
    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or {}
    specs = extract_specs(sim)
    sizing_lines = summarize_sizing(final_state.get("sizing") or {})
    netlist_lines = summarize_netlist(final_state.get("netlist"))
    reasons = pass_fail_reasons(sim)

    print("")
    print(f"=== Demo-Safe Case: {case_name} ===")
    print(f"Topology chosen: {final_state.get('selected_topology')}")
    selected = final_state.get("selected_topologies") or []
    if selected:
        print("Stage topologies: " + ", ".join(selected))
    print("Sizing decisions:")
    for line in sizing_lines:
        print(f"  - {line}")
    print("Generated netlist:")
    for line in netlist_lines:
        print(f"  {line}")
    if sim.get("simulation_skipped"):
        print(f"Simulation status: SKIPPED ({sim.get('skip_reason')})")
    else:
        sim_failed = (sim.get("returncode") not in (None, 0)) or bool(final_state.get("simulation_error"))
        print(
            "Simulation status: "
            f"{'FAILED' if sim_failed else 'COMPLETE'} "
            f"(returncode={sim.get('returncode')})"
        )
    print(f"Extracted specs: {specs if specs else 'none'}")
    print(
        "Verification summary: "
        f"{verification.get('passes', 0)} pass / {verification.get('fails', 0)} fail / "
        f"{verification.get('unknown', 0)} unknown"
    )
    print("Pass/fail reasons:")
    for reason in reasons:
        print(f"  - {reason}")


def run_demo_safe(profile_name: str = "ti_safe", cases=None, max_cases: int = None) -> list:
    if cases:
        selected_cases = list(cases)
    elif profile_name:
        selected_cases = get_demo_profile(profile_name)
    else:
        selected_cases = list(DEMO_SAFE_CASES)

    if max_cases is None:
        max_cases = max(1, int(os.getenv("DEMO_SAFE_MAX_CASES", "6")))
    if len(selected_cases) > max_cases:
        print(f"Demo-safe runtime guard: limiting run to first {max_cases} cases out of {len(selected_cases)}.")
        selected_cases = selected_cases[:max_cases]

    if not selected_cases:
        raise SystemExit("No demo-safe cases selected.")

    print("=== Demo-Safe Run ===")
    print("This command runs a curated high-confidence set for sponsor-facing demos.")
    print("Cases: " + ", ".join(selected_cases))

    summaries = []
    for case_name in selected_cases:
        final_state = run_case(case_name)
        _print_demo_safe_case_summary(case_name, final_state)

        sim = final_state.get("simulation_results") or {}
        verification = sim.get("verification_summary") or {}
        summaries.append(
            {
                "case": case_name,
                "status": final_state.get("status"),
                "topology": final_state.get("selected_topology"),
                "simulation_skipped": bool(sim.get("simulation_skipped")),
                "verification_passes": verification.get("passes", 0),
                "verification_fails": verification.get("fails", 0),
            }
        )

    total = len(summaries)
    pass_count = sum(1 for item in summaries if int(item.get("verification_fails", 0) or 0) == 0)
    skipped_count = sum(1 for item in summaries if item.get("simulation_skipped"))

    print("")
    print("=== Demo-Safe Rollup ===")
    for item in summaries:
        print(
            f"- {item['case']}: status={item['status']}, topology={item['topology']}, "
            f"verification={item['verification_passes']}p/{item['verification_fails']}f, "
            f"sim_skipped={item['simulation_skipped']}"
        )
    print(f"Overall: {pass_count}/{total} cases with zero verification fails; {skipped_count}/{total} skipped simulation.")
    return summaries


def _write_text_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(content)


def _write_json_file(path: str, payload: dict) -> None:
    _write_text_file(path, dumps_pretty(payload) + "\n")


def _showcase_latest_prefix(backup: bool) -> str:
    return "latest_showcase_backup" if backup else "latest_showcase"


def _publish_latest_showcase_files(backup: bool, rollup_markdown: str, rollup_payload: dict, case_summaries: list[dict]) -> None:
    base_dir = os.path.join("artifacts", "showcase_runs")
    os.makedirs(base_dir, exist_ok=True)
    prefix = _showcase_latest_prefix(backup)

    _write_text_file(os.path.join(base_dir, f"{prefix}_summary.md"), rollup_markdown)
    _write_json_file(os.path.join(base_dir, f"{prefix}_summary.json"), rollup_payload)
    _write_json_file(
        os.path.join(base_dir, f"{prefix}_index.json"),
        {
            "mode": rollup_payload.get("mode"),
            "out_dir": rollup_payload.get("out_dir"),
            "primary_command": FINAL_SHOWCASE_PRIMARY_COMMAND,
            "backup_command": FINAL_SHOWCASE_BACKUP_COMMAND,
            "case_summaries": [
                {
                    "case": item.get("case"),
                    "display_name": item.get("display_name"),
                    "showcase_markdown_path": item.get("showcase_markdown_path"),
                    "showcase_json_path": item.get("showcase_json_path"),
                    "artifact_dir": item.get("artifact_dir"),
                    "recommended_visuals": item.get("recommended_visuals"),
                }
                for item in case_summaries
            ],
        },
    )

    cases_dir = os.path.join(base_dir, f"{prefix}_cases")
    os.makedirs(cases_dir, exist_ok=True)
    for item in case_summaries:
        markdown_path = item.get("showcase_markdown_path")
        json_path = item.get("showcase_json_path")
        if markdown_path and os.path.exists(markdown_path):
            shutil.copyfile(markdown_path, os.path.join(cases_dir, f"{item['case']}.md"))
        if json_path and os.path.exists(json_path):
            shutil.copyfile(json_path, os.path.join(cases_dir, f"{item['case']}.json"))


def _print_showcase_case_summary(index: int, total: int, summary: dict, *, backup: bool) -> None:
    print("")
    print("=" * 88)
    print(f"[{index}/{total}] {summary.get('display_name')} ({summary.get('case')})")
    print(f"Showcase role: {summary.get('showcase_role')}")
    print(f"Why selected: {summary.get('why_selected')}")
    print("")
    print("Topology choice:")
    print(f"  - selected topology: {summary.get('selected_topology')}")
    stage_topologies = summary.get("selected_topologies") or []
    if stage_topologies:
        print("  - stage topologies: " + ", ".join(stage_topologies))
    print(f"  - reasoning: {summary.get('topology_reasoning')}")
    print("")
    print("Stage summary:")
    for item in summary.get("stage_status_summary") or []:
        print(
            f"  - {item.get('agent')}: last_status={item.get('last_status')} "
            f"(executed {item.get('count')}x)"
        )
    if not summary.get("stage_status_summary"):
        print("  - no stage history recorded")
    print("")
    print("Sizing summary:")
    for line in summary.get("sizing_summary") or ["n/a"]:
        print(f"  - {line}")
    print("")
    if summary.get("simulation_skipped"):
        print("Simulation status:")
        print(f"  - skipped: {summary.get('skip_reason')}")
        if backup:
            print("  - backup mode outcome: artifact-ready, verification deferred by design")
    else:
        print("Simulation status:")
        print("  - completed")
        print("  - analyses: " + (", ".join(summary.get("analyses") or []) or "none"))
    print("")
    print("Extracted metrics:")
    metrics = summary.get("key_metrics") or {}
    if metrics:
        for key, value in metrics.items():
            print(f"  - {key}: {_fmt_value(value)}")
    else:
        print("  - none")
    print("")
    print("Requirement verdicts:")
    verdicts = summary.get("requirement_verdicts") or []
    if verdicts:
        for item in verdicts:
            print(
                "  - "
                f"{item.get('requirement')}: requested={_fmt_value(item.get('requested'))}, "
                f"measured={_fmt_value(item.get('measured'))}, "
                f"status={item.get('status')}, assessment={item.get('assessment')}"
            )
    else:
        print("  - none")
    print("")
    print(
        "Final result: "
        f"framework_status={summary.get('status')}, "
        f"overall_verdict={summary.get('overall_verdict')}, "
        f"verification_status={summary.get('verification_status')}"
    )
    if summary.get("artifact_dir"):
        print(f"Artifact dir: {summary.get('artifact_dir')}")
    for path in summary.get("recommended_visuals") or []:
        print(f"Recommended visual: {path}")
    if summary.get("showcase_markdown_path"):
        print(f"Sponsor summary: {summary.get('showcase_markdown_path')}")


def run_final_showcase(cases=None, *, backup: bool = False) -> dict:
    selected_cases = list(cases or FINAL_SHOWCASE_CASES)
    if not selected_cases:
        raise SystemExit("No showcase cases selected.")

    mode = "backup" if backup else "full"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join("artifacts", "showcase_runs", f"{stamp}_ti_final_showcase_{mode}")
    os.makedirs(out_dir, exist_ok=True)

    print("=== TI Final Showcase ===")
    print(f"Mode: {'backup artifact-generation' if backup else 'full verification'}")
    print(f"Primary command: {FINAL_SHOWCASE_PRIMARY_COMMAND}")
    print(f"Backup command: {FINAL_SHOWCASE_BACKUP_COMMAND}")
    print("Cases: " + ", ".join(selected_cases))
    print(f"Aggregate output dir: {out_dir}")

    case_summaries = []
    for index, case_name in enumerate(selected_cases, start=1):
        case_info = FINAL_SHOWCASE_CASE_DETAILS.get(case_name, {})
        print("")
        print("-" * 88)
        print(f"Preparing case {index}/{len(selected_cases)}: {case_name}")
        if case_info.get("demonstrates"):
            print(f"Demonstrates: {case_info['demonstrates']}")

        runtime_options = None
        if backup:
            runtime_options = {
                "force_skip_simulation": True,
                "skip_simulation_reason": (
                    "Backup showcase mode intentionally skipped ngspice execution. "
                    "Topology, sizing, netlist, and sponsor-review artifacts were still generated."
                ),
            }

        final_state = run_case(case_name, runtime_options=runtime_options)
        summary = build_showcase_case_summary(case_name, final_state, mode=mode)
        markdown = render_showcase_case_markdown(summary)

        case_dir = os.path.join(out_dir, "cases", case_name)
        os.makedirs(case_dir, exist_ok=True)
        showcase_markdown_path = os.path.join(case_dir, "showcase_summary.md")
        showcase_json_path = os.path.join(case_dir, "showcase_summary.json")
        summary["showcase_markdown_path"] = showcase_markdown_path
        summary["showcase_json_path"] = showcase_json_path
        _write_text_file(showcase_markdown_path, markdown)
        _write_json_file(showcase_json_path, summary)

        artifact_dir = summary.get("artifact_dir")
        if artifact_dir:
            reports_dir = os.path.join(artifact_dir, "reports")
            os.makedirs(reports_dir, exist_ok=True)
            _write_text_file(os.path.join(reports_dir, "showcase_summary.md"), markdown)
            _write_json_file(os.path.join(reports_dir, "showcase_summary.json"), summary)

        case_summaries.append(summary)
        _print_showcase_case_summary(index, len(selected_cases), summary, backup=backup)

    rollup_markdown = render_showcase_rollup_markdown(
        mode=mode,
        out_dir=out_dir,
        case_summaries=case_summaries,
    )
    rollup_payload = stable_summary_index(mode=mode, out_dir=out_dir, case_summaries=case_summaries)

    rollup_markdown_path = os.path.join(out_dir, "showcase_summary.md")
    rollup_json_path = os.path.join(out_dir, "showcase_summary.json")
    _write_text_file(rollup_markdown_path, rollup_markdown)
    _write_json_file(rollup_json_path, rollup_payload)
    _publish_latest_showcase_files(backup, rollup_markdown, rollup_payload, case_summaries)

    print("")
    print("=== TI Final Showcase Rollup ===")
    for item in case_summaries:
        print(
            f"- {item['case']}: verdict={item.get('overall_verdict')}, "
            f"verification={item.get('verification_status')}, "
            f"topology={item.get('selected_topology')}"
        )
    print(f"Aggregate showcase summary: {rollup_markdown_path}")
    print(
        "Stable latest summary: "
        + os.path.join("artifacts", "showcase_runs", f"{_showcase_latest_prefix(backup)}_summary.md")
    )

    return {
        "mode": mode,
        "out_dir": out_dir,
        "rollup_markdown_path": rollup_markdown_path,
        "rollup_json_path": rollup_json_path,
        "case_summaries": case_summaries,
    }


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description="I13 engineer-facing analog design assistant CLI.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list-cases", help="List available DESIGN_CASE values.")
    sub.add_parser("list-profiles", help="List available DEMO_PROFILE values.")

    preflight = sub.add_parser("preflight", help="Run environment preflight checks.")
    preflight.add_argument("--profile", default="ti_safe", help="Reserved for compatibility with prior preflight flows.")
    preflight.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any WARN or FAIL checks are present.",
    )

    demo_safe = sub.add_parser("demo-safe", help="Run curated high-confidence sponsor demo cases.")
    demo_safe.add_argument("--profile", default="ti_safe", help="Profile name if --cases is not specified.")
    demo_safe.add_argument(
        "--cases",
        default="",
        help="Comma-separated case keys. If omitted, uses the built-in demo-safe curated set.",
    )
    demo_safe.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Cap the number of demo-safe cases to run (runtime guard).",
    )

    showcase = sub.add_parser("showcase", help="Run the final curated TI showcase flow.")
    showcase.add_argument(
        "--cases",
        default="",
        help="Optional comma-separated override for the curated showcase case list.",
    )

    showcase_backup = sub.add_parser(
        "showcase-backup",
        help="Run the final curated TI showcase in artifact-only backup mode.",
    )
    showcase_backup.add_argument(
        "--cases",
        default="",
        help="Optional comma-separated override for the curated showcase case list.",
    )

    run_case_parser = sub.add_parser("run-case", help="Run one design case and print final report.")
    run_case_parser.add_argument("--case", default=os.getenv("DESIGN_CASE", "mirror"), help="Case key from demo catalog.")

    return parser


def main(argv=None):
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "list-cases":
        _list_cases()
        return

    if args.command == "list-profiles":
        _list_profiles()
        return

    if args.command == "preflight":
        report = run_preflight(args.profile)
        if report.get("counts", {}).get("FAIL", 0) > 0:
            raise SystemExit(1)
        if args.strict and report.get("counts", {}).get("WARN", 0) > 0:
            raise SystemExit(2)
        return

    if args.command == "demo-safe":
        selected_cases = [item.strip() for item in args.cases.split(",") if item.strip()]
        run_demo_safe(
            profile_name=args.profile,
            cases=selected_cases if selected_cases else None,
            max_cases=args.max_cases,
        )
        return

    if args.command == "showcase":
        selected_cases = [item.strip() for item in args.cases.split(",") if item.strip()]
        run_final_showcase(cases=selected_cases if selected_cases else None, backup=False)
        return

    if args.command == "showcase-backup":
        selected_cases = [item.strip() for item in args.cases.split(",") if item.strip()]
        run_final_showcase(cases=selected_cases if selected_cases else None, backup=True)
        return

    if args.command == "run-case":
        final_state = run_case(args.case)
        print(format_final_report(args.case, final_state))
        return

    # Backward-compatible environment-driven behavior for existing scripts.
    case_name = os.getenv("DESIGN_CASE", "mirror")
    if case_name.lower() in {"list", "ls"}:
        _list_cases()
        return
    if case_name.lower() in {"profiles", "profile_list"}:
        _list_profiles()
        return
    if case_name.lower() in {"preflight", "ti_preflight"}:
        profile = os.getenv("DEMO_PROFILE", "ti_safe")
        report = run_preflight(profile)
        if report.get("counts", {}).get("FAIL", 0) > 0:
            raise SystemExit(1)
        return
    if case_name.lower() in {"demo-safe", "demo_safe"}:
        run_demo_safe(
            profile_name=os.getenv("DEMO_PROFILE", "ti_safe"),
            cases=None,
            max_cases=max(1, int(os.getenv("DEMO_SAFE_MAX_CASES", "6"))),
        )
        return
    if case_name.lower() in {"showcase", "final_showcase", "ti_showcase"}:
        run_final_showcase(cases=None, backup=False)
        return
    if case_name.lower() in {"showcase-backup", "showcase_backup", "final_showcase_backup"}:
        run_final_showcase(cases=None, backup=True)
        return

    final_state = run_case(case_name)
    print(format_final_report(case_name, final_state))


def run_case(case_name: str, case_override: dict = None, llm_override=None, runtime_options: dict = None):
    case = get_demo_case(case_name)
    runtime_options = dict(runtime_options or {})
    if case_override:
        case = {**case, **case_override}
        if "constraints" in case_override and isinstance(case_override["constraints"], dict):
            merged_constraints = dict(case.get("constraints") or {})
            merged_constraints.update(case_override["constraints"])
            case["constraints"] = merged_constraints
        if "simulation_plan" in case_override and isinstance(case_override["simulation_plan"], dict):
            merged_plan = dict(case.get("simulation_plan") or {})
            merged_plan.update(case_override["simulation_plan"])
            case["simulation_plan"] = merged_plan

    memory = SharedMemory()
    memory.write("specification", case["specification"])
    memory.write("constraints", case["constraints"])
    memory.write(
        "case_metadata",
        {
            "case_key": case.get("case_key"),
            "display_name": case.get("display_name"),
            "forced_topology": case.get("forced_topology"),
            "demo_model": case.get("demo_model", "native"),
            "readiness": case.get("readiness", "stable"),
            "artifact_label": case.get("artifact_label"),
            "simulation_plan": case.get("simulation_plan", {}),
            "force_skip_simulation": bool(runtime_options.get("force_skip_simulation")),
            "skip_simulation_reason": runtime_options.get("skip_simulation_reason"),
        },
    )
    reference_catalog = load_reference_catalog(resolve_reference_paths())
    memory.write("reference_catalog_summary", reference_catalog.summary())

    if llm_override is not None:
        llm = llm_override
        llm_resolution = {
            "configured_backend": "override",
            "resolved_backend": "override",
            "fallback_used": False,
            "message": "Using caller-provided LLM override.",
        }
        print("[LLM] Using caller-provided LLM override.")
    else:
        resolved = build_llm()
        llm = resolved.llm
        llm_resolution = {
            "configured_backend": resolved.configured_backend,
            "resolved_backend": resolved.resolved_backend,
            "fallback_used": resolved.fallback_used,
            "message": resolved.message,
        }
    memory.write("llm_resolution", llm_resolution)

    topology_agent = TopologyAgent(llm=llm, reference_catalog=reference_catalog)
    sizing_agent = SizingAgent(llm=llm, reference_catalog=reference_catalog)
    constraint_agent = ConstraintAgent(reference_catalog=reference_catalog)
    netlist_agent = NetlistAgent(llm=llm, reference_catalog=reference_catalog)
    op_point_agent = OpPointAgent(reference_catalog=reference_catalog)
    simulation_agent = SimulationAgent(reference_catalog=reference_catalog)
    refinement_agent = RefinementAgent(llm=llm, reference_catalog=reference_catalog)

    orchestrator = OrchestrationAgent(
        memory=memory,
        topology_agent=topology_agent,
        sizing_agent=sizing_agent,
        constraint_agent=constraint_agent,
        netlist_agent=netlist_agent,
        op_point_agent=op_point_agent,
        simulation_agent=simulation_agent,
        refinement_agent=refinement_agent,
        max_iterations=7,
    )

    print(f"Running case: {case_name} -> {case.get('display_name')}")
    final_state = orchestrator.run()
    _write_artifact_report(case_name, final_state)
    return final_state


if __name__ == "__main__":
    main()
    
