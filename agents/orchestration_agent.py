# I13/agents/orchestration_agent.py

from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory
from core.topology_library import TOPOLOGY_LIBRARY


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
            if self.memory.read("selected_topology") is None:
                self.topology_agent.run(self.memory)

                if self.memory.read("status") != DesignStatus.TOPOLOGY_SELECTED:
                    return self.fail()
            else:
                self.memory.write("status", DesignStatus.TOPOLOGY_SELECTED)
                topology = self.memory.read("selected_topology")
                if topology in TOPOLOGY_LIBRARY and self.memory.read("constraint_template") is None:
                    self.memory.write("constraint_template", TOPOLOGY_LIBRARY[topology]["constraint_template"])

            # sizing
            if self.memory.read("sizing") is None:
                self.sizing_agent.run(self.memory)

                if self.memory.read("status") != DesignStatus.SIZING_COMPLETE:
                    return self.fail()
            else:
                self.memory.write("status", DesignStatus.SIZING_COMPLETE)

            # constraints
            _, report = self.constraint_agent.run(self.memory)

            if not report.passed:
                return self.fail()

            # simulation
            self.simulation_agent.run(self.memory)

            if self.memory.read("status") != DesignStatus.SIMULATION_COMPLETE:
                return self.fail()

            # refinement
            self.refinement_agent.run(self.memory)
            status = self.memory.read("status")

            if status == DesignStatus.REFINED:
                continue

            if status in (DesignStatus.REFINEMENT_SKIPPED, DesignStatus.REFINEMENT_NO_CHANGE):
                self.memory.write("status", DesignStatus.DESIGN_VALIDATED)
                return self.memory.get_full_state()

            return self.fail()

        self.memory.write("status", DesignStatus.DESIGN_INVALID_AFTER_RETRIES)

        return self.memory.get_full_state()

    def fail(self):
        self.memory.write("status", DesignStatus.ORCHESTRATION_FAILED)

        return self.memory.get_full_state()