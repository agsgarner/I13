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

        if not sim or not constraints or not sizing:
            memory.write("status", "refinement_skipped")
            memory.write(
                "refinement_report",
                {"changed": False, "reason": "Missing simulation, constraints, or sizing"},
            )
            return

        fc_target = constraints.get("target_fc_hz")
        # Prefer SPICE if available later; for now use analytic cutoff
        fc_sim = sim.get("fc_hz_spice") or sim.get("fc_hz_analytic")

        if not fc_target or not fc_sim:
            memory.write("status", "refinement_skipped")
            memory.write(
                "refinement_report",
                {"changed": False, "reason": "Missing cutoff frequency data"},
            )
            return

        ratio = fc_sim / fc_target

        new_R = sizing["R_ohm"] * ratio

        sizing["R_ohm"] = new_R

        memory.write("sizing", sizing)

        memory.write("refinement_report", {
            "changed": True,
            "new_R": new_R
        })
