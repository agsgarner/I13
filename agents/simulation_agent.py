#I13/agents/simulation_agent.py

from agents.base_agent import BaseAgent

class SimulationAgent(BaseAgent):
    """
    Placeholder simulation stage.
    """

    def run(self, memory):

        topology = memory.read("selected_topology")
        sizing = memory.read("sizing")

        if topology == "rc_lowpass":
            R = sizing["R_ohm"]
            C = sizing["C_f"]
            fc = 1 / (2 * 3.141592653589793 * R * C)

            simulation = {
                "estimated_fc_hz": fc
            }

            memory.write("simulation_data", simulation)
            memory.write("status", "simulation_complete")
            return

        memory.write("status", "simulation_failed")