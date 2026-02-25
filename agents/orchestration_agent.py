# I13/agents/orchestration_agent.py

from core.shared_memory import SharedMemory


class OrchestrationAgent:

    def __init__(
        self,
        memory,
        topology_agent,
        sizing_agent,
        constraint_agent,
        simulation_agent,
        refinement_agent
    ):

        self.memory = memory
        self.topology_agent = topology_agent
        self.sizing_agent = sizing_agent
        self.constraint_agent = constraint_agent
        self.simulation_agent = simulation_agent
        self.refinement_agent = refinement_agent

    def run(self):

        max_iterations = 3

        for iteration in range(max_iterations):

            print(f"Iteration {iteration+1}")

            # topology
            self.topology_agent.run(self.memory)

            if self.memory.read("status") != "topology_selected":
                return self.fail()

            # sizing
            self.sizing_agent.run(self.memory)

            if self.memory.read("status") != "sizing_complete":
                return self.fail()

            # constraints
            _, report = self.constraint_agent.run(self.memory)

            if not report.passed:
                return self.fail()

            # simulation
            self.simulation_agent.run(self.memory)

            if self.memory.read("status") != "simulation_complete":
                return self.fail()

            # refinement
            self.refinement_agent.run(self.memory)

            if self.memory.read("status") == "refined":
                continue

            self.memory.write("status", "design_validated")
            return self.memory.get_full_state()

        self.memory.write("status", "design_invalid_after_retries")

        return self.memory.get_full_state()

    def fail(self):

        self.memory.write("status", "orchestration_failed")

        return self.memory.get_full_state()