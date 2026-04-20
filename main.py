import os
import json

from agents.design_status import DesignStatus
from core.demo_catalog import get_demo_case, get_demo_profile, list_demo_cases, list_demo_profiles
from core.shared_memory import SharedMemory
from llm.local_llm_stub import LocalLLMStub

from agents.topology_agent import TopologyAgent
from agents.sizing_agent import SizingAgent
from agents.constraints_agent import ConstraintAgent
from agents.netlist_agent import NetlistAgent
from agents.op_point_agent import OpPointAgent
from agents.simulation_agent import SimulationAgent
from agents.refinement_agent import RefinementAgent
from agents.orchestration_agent import OrchestrationAgent


def build_llm():
    use_openai = os.getenv("USE_OPENAI", "0").strip() == "1"

    if use_openai:
        try:
            from llm.openai_llm import OpenAILLM

            llm = OpenAILLM(
                model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
                temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.2")),
            )
            print("[LLM] Using OpenAI backend.")
            return llm
        except Exception as exc:
            print(f"[LLM] OpenAI unavailable, falling back to LocalLLMStub: {exc}")

    print("[LLM] Using LocalLLMStub backend.")
    return LocalLLMStub()

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


def format_final_report(case_name: str, final_state: dict) -> str:
    sim = final_state.get("simulation_results") or {}
    refinement = final_state.get("refinement_report") or {}
    op_point = final_state.get("op_point_results") or {}
    constraints_report = final_state.get("constraints_report") or {}
    case_meta = final_state.get("case_metadata") or {}
    simulation_plan = case_meta.get("simulation_plan") or {}
    verification = sim.get("verification_summary") or final_state.get("verification_summary") or {}

    lines = [
        "",
        _banner_for_state(final_state),
        "=== Final Report ===",
        f"Case: {case_name}",
        f"Display name: {case_meta.get('display_name', 'n/a')}",
        f"Specification: {final_state.get('specification', 'n/a')}",
        f"Status: {final_state.get('status')}",
        f"Topology: {final_state.get('selected_topology')}",
        f"Stage topologies: {', '.join(final_state.get('selected_topologies') or [final_state.get('selected_topology') or 'n/a'])}",
        f"Iterations completed: {final_state.get('iteration', 0)}",
        f"Netlist source: {final_state.get('netlist_source', 'n/a')}",
    ]

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

    if case_meta.get("demo_model"):
        lines.append(f"Demo model: {case_meta.get('demo_model')}")
    if case_meta.get("readiness"):
        lines.append(f"Readiness: {case_meta.get('readiness')}")

    artifact_dir = sim.get("artifact_dir")
    if artifact_dir:
        lines.append(f"Latest artifact dir: {artifact_dir}")
    if sim.get("saved_netlist_path"):
        lines.append(f"Simulated netlist: {sim.get('saved_netlist_path')}")
        lines.append("Simulation provenance: metrics and plots below are derived from this artifact netlist.")
    if simulation_plan.get("analyses"):
        lines.append(f"Simulation intent: {simulation_plan.get('intent', 'n/a')}")
        lines.append("Planned analyses: " + ", ".join(simulation_plan["analyses"]))

    metric_rows = _format_metrics_block(sim)
    if metric_rows:
        lines.append("Metrics:")
        lines.extend(metric_rows)
    if sim.get("response_family"):
        lines.append(f"Response family: {sim.get('response_family')}")
    if sim.get("ac_characterization"):
        ac_char = sim.get("ac_characterization") or {}
        lines.append(
            "AC characterization: "
            f"shape={ac_char.get('response_shape', 'n/a')} "
            f"peak={_fmt_value(ac_char.get('peak_gain_db'), ' dB')} "
            f"f_peak={_fmt_value(ac_char.get('peak_frequency_hz'), ' Hz')}"
        )
    if sim.get("transient_characterization"):
        tran_char = sim.get("transient_characterization") or {}
        lines.append(
            "Transient characterization: "
            f"step={tran_char.get('step_detected')} "
            f"settling={_fmt_value(tran_char.get('settling_time_s'), ' s')} "
            f"overshoot={_fmt_value(tran_char.get('overshoot_pct'), ' %')}"
        )
    if sim.get("plot_validation_summary"):
        pv = sim.get("plot_validation_summary") or {}
        lines.append(
            "Plot validation: "
            f"{pv.get('passes', 0)} pass, {pv.get('fails', 0)} fail "
            f"(overall_pass={pv.get('overall_pass')})"
        )

    plots = []
    for key in ("ac_plot", "tran_plot", "dc_plot"):
        if sim.get(key):
            plots.append(f"{key}: {sim.get(key)}")
    if plots:
        lines.append("Plots: " + ", ".join(plots))

    if verification:
        lines.append(
            "Verification: "
            f"{verification.get('passes', 0)} pass, "
            f"{verification.get('fails', 0)} fail, "
            f"{verification.get('unknown', 0)} unknown"
        )
    if op_point:
        lines.append(
            "OP sizing pass: "
            f"supported={op_point.get('supported')} changed={op_point.get('changed')} "
            f"pass_index={op_point.get('pass_index', 'n/a')}"
        )

    llm_calls = [
        item for item in (final_state.get("history") or [])
        if item.get("event") == "llm_call"
    ]
    if llm_calls:
        successful = sum(1 for item in llm_calls if (item.get("data") or {}).get("ok") is True)
        lines.append(f"LLM calls: {successful}/{len(llm_calls)} successful")

    if constraints_report.get("warnings"):
        lines.append("Constraint warnings:")
        lines.extend(f"  - {warning}" for warning in constraints_report["warnings"])

    if refinement.get("notes"):
        lines.append("Refinement notes:")
        lines.extend(f"  - {note}" for note in refinement["notes"])

    error_fields = [
        ("Topology error", final_state.get("topology_error")),
        ("Sizing error", final_state.get("sizing_error")),
        ("Constraint issues", constraints_report.get("issues")),
        ("Netlist error", final_state.get("netlist_error")),
        ("Simulation error", final_state.get("simulation_error")),
        ("Parser warning", sim.get("parser_warning")),
    ]
    for label, value in error_fields:
        if value:
            if isinstance(value, list):
                lines.append(f"{label}: " + "; ".join(str(item) for item in value))
            else:
                lines.append(f"{label}: {value}")

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
        "simulation_intent": (case_meta.get("simulation_plan") or {}).get("intent"),
        "analyses": sim.get("analyses") or (case_meta.get("simulation_plan") or {}).get("analyses", []),
        "targets": {
            "gain_db": constraints.get("target_gain_db"),
            "bandwidth_hz": constraints.get("target_bw_hz"),
            "cutoff_hz": constraints.get("target_fc_hz"),
            "center_hz": constraints.get("target_center_hz"),
            "ugbw_hz": constraints.get("target_ugbw_hz"),
            "power_limit_mw": constraints.get("power_limit_mw"),
            "oscillation_hz": constraints.get("target_osc_hz"),
            "decision_delay_s": constraints.get("target_decision_delay_s"),
        },
        "measured": {
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
    report_text = format_final_report(case_name, final_state) + "\n"
    with open(os.path.join(artifact_dir, "final_report.txt"), "w") as f:
        f.write(report_text)
    with open(os.path.join(artifact_dir, "metrics_summary.json"), "w") as f:
        json.dump(_artifact_summary(case_name, final_state), f, indent=2)


def main():
    case_name = os.getenv("DESIGN_CASE", "mirror")
    if case_name.lower() in {"list", "ls"}:
        print("Available DESIGN_CASE values:")
        for item in list_demo_cases():
            print(
                f"- {item['key']}: {item['display_name']} "
                f"(topology={item['forced_topology']}, model={item['demo_model']}, readiness={item['readiness']})"
            )
        return
    if case_name.lower() in {"profiles", "profile_list"}:
        print("Available DEMO_PROFILE values:")
        for item in list_demo_profiles():
            print(f"- {item['name']}: {', '.join(item['cases'])}")
        return
    if case_name.lower() in {"preflight", "ti_preflight"}:
        profile = os.getenv("DEMO_PROFILE", "ti_safe")
        run_preflight(profile)
        return
    final_state = run_case(case_name)
    print(format_final_report(case_name, final_state))


def run_preflight(profile_name: str):
    cases = get_demo_profile(profile_name)
    print(f"Running preflight for DEMO_PROFILE={profile_name}")
    failures = []
    for case_name in cases:
        final_state = run_case(case_name)
        sim = final_state.get("simulation_results") or {}
        verification = sim.get("verification_summary") or {}
        print(
            f"- {case_name}: status={final_state.get('status')} "
            f"verification={verification.get('passes', 0)}p/{verification.get('fails', 0)}f"
        )
        if final_state.get("status") != DesignStatus.DESIGN_VALIDATED or verification.get("fails", 0) > 0:
            failures.append(case_name)

    if failures:
        raise SystemExit(f"Preflight failed for: {', '.join(failures)}")
    print("Preflight passed.")


def run_case(case_name: str, case_override: dict = None, llm_override=None):
    case = get_demo_case(case_name)
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
        },
    )

    llm = llm_override if llm_override is not None else build_llm()

    topology_agent = TopologyAgent(llm=llm)
    sizing_agent = SizingAgent(llm=llm)
    constraint_agent = ConstraintAgent()
    netlist_agent = NetlistAgent(llm=llm)
    op_point_agent = OpPointAgent()
    simulation_agent = SimulationAgent()
    refinement_agent = RefinementAgent(llm=llm)

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
    
