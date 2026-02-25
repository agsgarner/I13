# I13/agents/orchestration_agent.py

from core.shared_memory import SharedMemory


class OrchestrationAgent:
    """
    Controls workflow between agents.
    """

    def __init__(self, memory, topology_agent, sizing_agent, constraint_agent, simulation_agent):
        self.memory = memory
        self.topology_agent = topology_agent
        self.sizing_agent = sizing_agent
        self.constraint_agent = constraint_agent
        self.simulation_agent = simulation_agent

    def run(self):

        max_attempts = 3

        for attempt in range(max_attempts):

            # Select topology
            self.topology_agent.run(self.memory)

            if self.memory.read("status") != "topology_selected":
                self.memory.write("status", "orchestration_failed")
                return self.memory.get_full_state()
            
            # Generate sizing
            self.sizing_agent.run(self.memory)

            if self.memory.read("status") != "sizing_complete":
                self.memory.write("status", "sizing_failed")
                return self.memory.get_full_state()
            
            # Validate constratints
            _, report = self.constraint_agent.run(self.memory)

            if report.passed:

                # Simulation
                self.simulation_agent.run(self.memory)

                self.memory.write("status", "design_validated")
                return self.memory.get_full_state()

        # If all attempts fail
        self.memory.write("status", "design_invalid_after_retries")
        return self.memory.get_full_state()