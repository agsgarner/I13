# I13/main.py

from core.shared_memory import SharedMemory

from llm.local_llm_stub import LocalLLMStub

from agents.topology_agent import TopologyAgent
from agents.sizing_agent import SizingAgent
from agents.constraints_agent import ConstraintAgent
from agents.simulation_agent import SimulationAgent
from agents.refinement_agent import RefinementAgent
from agents.orchestration_agent import OrchestrationAgent


# -------------------------------------------------------
# Pretty Terminal Output
# -------------------------------------------------------

def print_banner():
    print("\n" + "=" * 70)
    print("     MULTI-AGENT ANALOG CIRCUIT DESIGN SYSTEM")
    print("=" * 70 + "\n")


def summarize_design(state):

    print("\n" + "-" * 70)
    print("FINAL DESIGN SUMMARY")
    print("-" * 70)

    # Specification
    print("\n[1] Specification")
    print("   ", state.get("specification"))

    # Topology
    print("\n[2] Topology Selection")
    print("    Selected:", state.get("selected_topology"))
    print("    LLM Confidence:", state.get("topology_confidence"))

    # Sizing
    print("\n[3] Sizing Parameters")
    sizing = state.get("sizing", {})
    for k, v in sizing.items():
        print(f"    {k}: {v}")

    # Constraint Report
    print("\n[4] Constraint Evaluation")
    report = state.get("constraints_report", {})
    print("    Passed:", report.get("passed"))
    print("    Completeness Score:", report.get("completeness_score"))

    if report.get("issues"):
        print("    Issues:")
        for issue in report.get("issues"):
            print("       -", issue)

    if report.get("warnings"):
        print("    Warnings:")
        for warn in report.get("warnings"):
            print("       -", warn)

    # Simulation Results
    print("\n[5] Simulation Results")
    sim = state.get("simulation_results", {})
    for k, v in sim.items():
        print(f"    {k}: {v}")

    # Refinement
    print("\n[6] Refinement Analysis")
    refinement_issues = state.get("refinement_issues", [])
    if refinement_issues:
        print("    Issues Identified:")
        for issue in refinement_issues:
            print("       -", issue)
    else:
        print("    No refinement issues detected.")

    # History
    print("\n[7] Execution History")
    history = state.get("history", [])
    print("    Total Events:", len(history))

    print("\n    Last 5 Events:")
    for event in history[-5:]:
        print("       -", event)

    # Final Status
    print("\n[8] Final System Status")
    print("    ", state.get("status"))

    print("\n" + "-" * 70 + "\n")


# -------------------------------------------------------
# Main Entry
# -------------------------------------------------------

def main():

    print_banner()

    # Initialize memory
    memory = SharedMemory()

    # Example specification
    memory.write("specification", "Design a lowpass filter with 1kHz cutoff")

    memory.write("constraints", {
        "circuit_type": "rc_lowpass",
        "target_fc_hz": 1000
    })

    # Initialize LLM
    llm = LocalLLMStub()

    # Initialize agents
    topology_agent = TopologyAgent(llm)
    sizing_agent = SizingAgent()
    constraint_agent = ConstraintAgent()
    simulation_agent = SimulationAgent()
    refinement_agent = RefinementAgent(llm)

    # Orchestrator
    orchestrator = OrchestrationAgent(
        memory,
        topology_agent,
        sizing_agent,
        constraint_agent,
        simulation_agent,
        refinement_agent
    )

    print("Starting autonomous design loop...\n")

    # Run system
    final_state = orchestrator.run()

    print("\nDesign loop complete.")

    # Print detailed results
    summarize_design(final_state)


if __name__ == "__main__":
    main()