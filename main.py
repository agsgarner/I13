import os
import json

from agents.design_status import DesignStatus
from core.demo_catalog import get_demo_case, list_demo_cases
from core.shared_memory import SharedMemory
from llm.local_llm_stub import LocalLLMStub

from agents.topology_agent import TopologyAgent
from agents.sizing_agent import SizingAgent
from agents.constraints_agent import ConstraintAgent
from agents.netlist_agent import NetlistAgent
from agents.simulation_agent import SimulationAgent
from agents.refinement_agent import RefinementAgent
from agents.orchestration_agent import OrchestrationAgent


def build_llm():
    use_openai = os.getenv("USE_OPENAI", "0").strip() == "1"

    if use_openai:
        try:
            from llm.openai_llm import OpenAILLM

            llm = OpenAILLM(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
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
        ("Qfinal", "q_final_v", " V"),
        ("QBfinal", "qb_final_v", " V"),
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
    constraints_report = final_state.get("constraints_report") or {}
    case_meta = final_state.get("case_metadata") or {}
    simulation_plan = case_meta.get("simulation_plan") or {}

    lines = [
        "",
        _banner_for_state(final_state),
        "=== Final Report ===",
        f"Case: {case_name}",
        f"Display name: {case_meta.get('display_name', 'n/a')}",
        f"Status: {final_state.get('status')}",
        f"Topology: {final_state.get('selected_topology')}",
        f"Iterations completed: {final_state.get('iteration', 0)}",
        f"Netlist source: {final_state.get('netlist_source', 'n/a')}",
    ]

    if case_meta.get("demo_model"):
        lines.append(f"Demo model: {case_meta.get('demo_model')}")

    artifact_dir = sim.get("artifact_dir")
    if artifact_dir:
        lines.append(f"Latest artifact dir: {artifact_dir}")
    if simulation_plan.get("analyses"):
        lines.append(f"Simulation intent: {simulation_plan.get('intent', 'n/a')}")
        lines.append("Planned analyses: " + ", ".join(simulation_plan["analyses"]))

    metric_rows = _format_metrics_block(sim)
    if metric_rows:
        lines.append("Metrics:")
        lines.extend(metric_rows)
    if sim.get("response_family"):
        lines.append(f"Response family: {sim.get('response_family')}")

    plots = []
    for key in ("ac_plot", "tran_plot", "dc_plot"):
        if sim.get(key):
            plots.append(f"{key}: {sim.get(key)}")
    if plots:
        lines.append("Plots: " + ", ".join(plots))

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
    return {
        "case": case_name,
        "display_name": case_meta.get("display_name"),
        "topology": final_state.get("selected_topology"),
        "status": final_state.get("status"),
        "simulation_intent": (case_meta.get("simulation_plan") or {}).get("intent"),
        "analyses": sim.get("analyses") or (case_meta.get("simulation_plan") or {}).get("analyses", []),
        "targets": {
            "gain_db": constraints.get("target_gain_db"),
            "bandwidth_hz": constraints.get("target_bw_hz"),
            "cutoff_hz": constraints.get("target_fc_hz"),
            "center_hz": constraints.get("target_center_hz"),
            "power_limit_mw": constraints.get("power_limit_mw"),
            "oscillation_hz": constraints.get("target_oscillation_hz"),
        },
        "measured": {
            "gain_db": sim.get("gain_db"),
            "bandwidth_hz": sim.get("bandwidth_hz"),
            "cutoff_hz": sim.get("fc_hz"),
            "center_hz": sim.get("center_hz"),
            "power_mw": sim.get("power_mw"),
            "power_margin_mw": sim.get("power_margin_mw"),
            "oscillation_hz": sim.get("oscillation_hz"),
        },
        "checks": {
            "power_limit_ok": sim.get("power_limit_ok"),
            "write_ok": sim.get("write_ok"),
        },
        "artifacts": {
            "ac_plot": sim.get("ac_plot"),
            "tran_plot": sim.get("tran_plot"),
            "dc_plot": sim.get("dc_plot"),
            "saved_netlist_path": sim.get("saved_netlist_path"),
            "log_path": sim.get("log_path"),
        },
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
                f"(topology={item['forced_topology']}, model={item['demo_model']})"
            )
        return
    final_state = run_case(case_name)
    print(format_final_report(case_name, final_state))


def run_case(case_name: str):
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
            "artifact_label": case.get("artifact_label"),
            "simulation_plan": case.get("simulation_plan", {}),
        },
    )

    llm = build_llm()

    topology_agent = TopologyAgent(llm=llm)
    sizing_agent = SizingAgent()
    constraint_agent = ConstraintAgent()
    netlist_agent = NetlistAgent(llm=llm)
    simulation_agent = SimulationAgent()
    refinement_agent = RefinementAgent(llm=llm)

    orchestrator = OrchestrationAgent(
        memory=memory,
        topology_agent=topology_agent,
        sizing_agent=sizing_agent,
        constraint_agent=constraint_agent,
        netlist_agent=netlist_agent,
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
    
