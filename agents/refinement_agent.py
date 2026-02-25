# I13/agents/refinement_agent.py

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory


class RefinementAgent(BaseAgent):

    def __init__(self, llm):
        super().__init__(llm)

    def run(self, memory: SharedMemory):

        sim = memory.read("simulation_results")
        constraints = memory.read("constraints")
        sizing = memory.read("sizing")
        topology = memory.read("selected_topology")

        if topology != "rc_lowpass":
            memory.write("status", "refinement_skipped")
            return

        fc_target = constraints["target_fc_hz"]
        fc_sim = sim["fc_hz"]

        ratio = fc_sim / fc_target

        new_R = sizing["R_ohm"] * ratio

        sizing["R_ohm"] = new_R

        memory.write("sizing", sizing)

        memory.write("refinement_report", {
            "changed": True,
            "new_R": new_R
        })
