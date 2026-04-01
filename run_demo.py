from core.shared_memory import SharedMemory
from core.demo_catalog import get_demo_case

from agents.topology_agent import TopologyAgent
from agents.sizing_agent import SizingAgent
from agents.constraints_agent import ConstraintAgent
from agents.netlist_agent import NetlistAgent
from agents.simulation_agent import SimulationAgent
from agents.refinement_agent import RefinementAgent
from agents.orchestration_agent import OrchestrationAgent


def main():
    case = get_demo_case("cs_amp")

    memory = SharedMemory()
    memory.write("specification", case["specification"])
    memory.write("constraints", case["constraints"])
    memory.write("case_metadata", {
        "forced_topology": case.get("forced_topology"),
        "case_key": case.get("case_key"),
        "display_name": case.get("display_name"),
    })

    topology_agent = TopologyAgent(llm=None)
    sizing_agent = SizingAgent(llm=None)
    constraint_agent = ConstraintAgent(llm=None)
    netlist_agent = NetlistAgent(llm=None)
    simulation_agent = SimulationAgent(llm=None)
    refinement_agent = RefinementAgent(llm=None)

    orchestrator = OrchestrationAgent(
        memory=memory,
        topology_agent=topology_agent,
        sizing_agent=sizing_agent,
        constraint_agent=constraint_agent,
        netlist_agent=netlist_agent,
        simulation_agent=simulation_agent,
        refinement_agent=refinement_agent,
        max_iterations=6,
    )

    final_state = orchestrator.run()

    print("\n=== FINAL STATUS ===")
    print(final_state.get("status"))

    print("\n=== SELECTED TOPOLOGY ===")
    print(final_state.get("selected_topology"))

    print("\n=== SIZING ===")
    print(final_state.get("sizing"))

    print("\n=== CONSTRAINT REPORT ===")
    print(final_state.get("constraints_report"))

    print("\n=== REFINEMENT REPORT ===")
    print(final_state.get("refinement_report"))

    print("\n=== SIMULATION RESULTS ===")
    sim = final_state.get("simulation_results") or {}
    keys_to_show = [
        "gain_db",
        "bandwidth_hz",
        "power_mw",
        "artifact_dir",
        "ac_csv",
        "ac_plot",
        "log_path",
        "parser_warning",
    ]
    for key in keys_to_show:
        print(f"{key}: {sim.get(key)}")


if __name__ == "__main__":
    main()
