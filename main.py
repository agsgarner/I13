# I13/main.py

import os

import argparse

from core.shared_memory import SharedMemory

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
    """
    Select a remote provider by env var, then fall back to the local stub so
    the demo still runs reliably without API/network access.
    """
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    use_qwen = os.getenv("USE_QWEN", "0").strip() == "1"
    use_openai = os.getenv("USE_OPENAI", "0").strip() == "1"

    if provider == "qwen" or use_qwen:
        try:
            from llm.qwen_llm import QwenLLM

            qwen_model = os.getenv("QWEN_MODEL", "qwen-turbo")
            llm = QwenLLM(model=qwen_model)
            print("[LLM] Using Qwen backend.")
            return llm
        except Exception as exc:
            print(f"[LLM] Qwen unavailable, falling back to LocalLLMStub: {exc}")

    if provider == "openai" or use_openai:
        try:
            from llm.openai_llm import OpenAILLM

            llm = OpenAILLM(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
            print("[LLM] Using OpenAI backend.")
            return llm
        except Exception as exc:
            print(f"[LLM] OpenAI unavailable, falling back to LocalLLMStub: {exc}")

    print("[LLM] Using LocalLLMStub backend.")
    return LocalLLMStub()


def print_banner():
    print("\n" + "=" * 72)
    print("        MULTI-AGENT ANALOG CIRCUIT DESIGN SYSTEM")
    print("=" * 72 + "\n")


def summarize_design(state):
    print("\n" + "-" * 72)
    print("FINAL DESIGN SUMMARY")
    print("-" * 72)

    print("\n[1] Specification")
    print("   ", state.get("specification"))

    print("\n[2] Topology")
    print("   selected_topology:", state.get("selected_topology"))
    print("   topology_confidence:", state.get("topology_confidence"))
    print("   topology_reasoning:", state.get("topology_reasoning"))

    print("\n[3] Constraints")
    for k, v in (state.get("constraints") or {}).items():
        print(f"   {k}: {v}")

    print("\n[4] Sizing")
    for k, v in (state.get("sizing") or {}).items():
        print(f"   {k}: {v}")

    print("\n[5] Constraint Report")
    report = state.get("constraints_report") or {}
    print("   passed:", report.get("passed"))
    for issue in report.get("issues", []):
        print("   issue:", issue)
    for warning in report.get("warnings", []):
        print("   warning:", warning)

    print("\n[6] Netlist")
    print("   source:", state.get("netlist_source"))
    netlist = state.get("netlist")
    if netlist:
        print(netlist)

    print("\n[7] Simulation Results")
    sim = state.get("simulation_results") or {}
    ordered_keys = [
        "returncode",
        "saved_netlist_path",
        "artifact_dir",
        "ac_csv",
        "ac_plot",
        "ac_points",
        "tran_in_csv",
        "tran_out_csv",
        "tran_plot",
        "tran_points",
        "fc_hz_from_ac",
        "fc_hz_formula",
        "fc_hz",
        "parser_warning",
        "ngspice_path",
    ]
    shown = set()
    for k in ordered_keys:
        if k in sim:
            print(f"   {k}: {sim[k]}")
            shown.add(k)

    for k, v in sim.items():
        if k not in shown and k not in ("stdout", "stderr", "ac_preview", "tran_preview"):
            print(f"   {k}: {v}")

    if sim.get("ac_preview"):
        print("   ac_preview:")
        for line in sim["ac_preview"]:
            print("      ", line)

    if sim.get("tran_preview"):
        print("   tran_preview:")
        for line in sim["tran_preview"]:
            print("      ", line)

    print("\n[8] Refinement Report")
    refinement = state.get("refinement_report") or {}
    print("   changed:", refinement.get("changed"))
    for note in refinement.get("notes", []):
        print("   note:", note)

    print("\n[9] Final Status")
    print("   ", state.get("status"))

    print("\n[10] Iteration Count")
    print("   ", state.get("iteration"))

    print("\n" + "-" * 72 + "\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the multi-agent analog design loop from terminal inputs."
    )
    parser.add_argument(
        "--demo-case",
        type=str,
        default="",
        help="Use a predefined case from core.demo_catalog (e.g., rc, cs_amp, mirror, diff_pair, opamp).",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List available demo cases and exit.",
    )
    parser.add_argument(
        "--spec",
        type=str,
        default="Design a lowpass filter with 1kHz cutoff",
        help="Natural-language design specification.",
    )
    parser.add_argument(
        "--circuit-type",
        type=str,
        default="rc_lowpass",
        help="Constraint circuit type (e.g., rc_lowpass, common_source).",
    )
    parser.add_argument(
        "--target-fc",
        type=float,
        default=1000.0,
        help="Target cutoff frequency in Hz.",
    )
    return parser.parse_args()


def main():
    print_banner()
    args = parse_args()

    if args.list_cases:
        print("Available demo cases:")
        for item in list_demo_cases():
            print(f"- {item['key']}: {item['display_name']}")
        return

    memory = SharedMemory()

    if args.demo_case:
        case = get_demo_case(args.demo_case)
        memory.write("specification", case["specification"])
        memory.write("constraints", case["constraints"])
        memory.write("case_metadata", {
            "forced_topology": case.get("forced_topology"),
            "case_key": case.get("case_key"),
            "display_name": case.get("display_name"),
        })
    else:
        memory.write(
            "specification",
            args.spec,
        )

        memory.write(
            "constraints",
            {
                "circuit_type": args.circuit_type,
                "target_fc_hz": float(args.target_fc),
                "fixed_cap_f": 10e-9,
                "vin_ac": 1.0,
                "vin_step": 1.0,
            }
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
        max_iterations=3,
    )

    print("Starting autonomous design workflow...\n")
    final_state = orchestrator.run()
    print("Workflow complete.\n")

    summarize_design(final_state)


if __name__ == "__main__":
    main()
