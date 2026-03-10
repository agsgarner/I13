# I13/agents/simulation_agent.py

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory
import math


class SimulationAgent(BaseAgent):

    def run(self, memory: SharedMemory):

        topology = memory.read("selected_topology")
        sizing = memory.read("sizing")

        if topology == "rc_lowpass" and sizing:

            R = sizing["R_ohm"]
            C = sizing["C_f"]

            fc = 1 / (2 * math.pi * R * C)

            results = {
                "fc_hz": fc,
                "gain_db": 0,
                "power_mw": 0
            }

            memory.write("simulation_results", results)
            memory.write("status", DesignStatus.SIMULATION_COMPLETE)

            return results

        memory.write("status", DesignStatus.SIMULATION_FAILED)
        return None