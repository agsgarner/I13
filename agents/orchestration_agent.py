# I13/agents/orchestration_agent.py

from flow.design_flow import build_design_flow


class OrchestrationAgent:
    def __init__(
        self,
        memory,
        topology_agent,
        sizing_agent,
        constraint_agent,
        netlist_agent,
        simulation_agent,
        refinement_agent,
        max_iterations=3,
    ):
        self.memory = memory
        self.flow = build_design_flow(
            topology_agent=topology_agent,
            sizing_agent=sizing_agent,
            constraint_agent=constraint_agent,
            netlist_agent=netlist_agent,
            simulation_agent=simulation_agent,
            refinement_agent=refinement_agent,
            max_iterations=max_iterations,
        )

    def run(self):
        self.flow.run(self.memory)
        return self.memory.get_full_state()