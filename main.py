# I13/main.py

import os

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


def get_demo_case(case_name: str):
    cases = {
        "rc": {
            "specification": "Design a first-order low-pass filter with approximately 1 kHz cutoff.",
            "constraints": {
                "target_fc_hz": 1000.0,
                "fixed_cap_f": 10e-9,
                "vin_ac": 1.0,
                "vin_step": 1.0,
            },
        },
        "cs_amp": {
            "specification": "Design a single-stage common-source amplifier for moderate gain.",
            "constraints": {
                "supply_v": 1.8,
                "target_gain_db": 20.0,
                "target_bw_hz": 1e6,
                "power_limit_mw": 2.0,
                "vin_dc": 0.75,
                "vin_ac": 1e-3,
                "load_cap_f": 1e-12,
                "target_vov_v": 0.2,
            },
        },
        "mirror": {
            "specification": "Design a MOS current mirror to generate 100 uA output current.",
            "constraints": {
                "supply_v": 1.8,
                "target_iout_a": 100e-6,
                "mirror_ratio": 1.0,
                "compliance_v": 0.8,
                "target_vov_v": 0.2,
            },
        },
        "opamp": {
            "specification": "Design a two-stage op amp with 60 dB gain and 10 MHz UGBW.",
            "constraints": {
                "supply_v": 1.8,
                "target_gain_db": 60.0,
                "target_ugbw_hz": 10e6,
                "phase_margin_deg": 60.0,
                "load_cap_f": 1e-12,
                "power_limit_mw": 2.0,
                "target_slew_v_per_us": 5.0,
            },
        },
    }
    return cases[case_name]


def _fmt_value(value, unit=""):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}{unit}"
    return f"{value}{unit}"


def format_final_report(case_name: str, final_state: dict) -> str:
    sim = final_state.get("simulation_results") or {}
    refinement = final_state.get("refinement_report") or {}
    constraints_report = final_state.get("constraints_report") or {}

    lines = [
        "",
        "=== Final Report ===",
        f"Case: {case_name}",
        f"Status: {final_state.get('status')}",
        f"Topology: {final_state.get('selected_topology')}",
        f"Iterations completed: {final_state.get('iteration', 0)}",
        f"Netlist source: {final_state.get('netlist_source', 'n/a')}",
    ]

    artifact_dir = sim.get("artifact_dir")
    if artifact_dir:
        lines.append(f"Latest artifact dir: {artifact_dir}")

    metrics = []
    if sim.get("gain_db") is not None:
        metrics.append(f"Gain: {_fmt_value(sim.get('gain_db'), ' dB')}")
    if sim.get("bandwidth_hz") is not None:
        metrics.append(f"Bandwidth: {_fmt_value(sim.get('bandwidth_hz'), ' Hz')}")
    if sim.get("fc_hz") is not None:
        metrics.append(f"Cutoff: {_fmt_value(sim.get('fc_hz'), ' Hz')}")
    if sim.get("power_mw") is not None:
        metrics.append(f"Power: {_fmt_value(sim.get('power_mw'), ' mW')}")
    if sim.get("iout_a") is not None:
        metrics.append(f"Iout: {_fmt_value(sim.get('iout_a'), ' A')}")
    if metrics:
        lines.append("Metrics: " + ", ".join(metrics))

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

    return "\n".join(lines)


def main():
    case_name = os.getenv("DESIGN_CASE", "cs_amp")
    case = get_demo_case(case_name)

    memory = SharedMemory()
    memory.write("specification", case["specification"])
    memory.write("constraints", case["constraints"])

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

    print(f"Running case: {case_name}")
    final_state = orchestrator.run()
    print(format_final_report(case_name, final_state))


if __name__ == "__main__":
    main()
    
