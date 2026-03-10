# I13/agents/refinement_agent.py

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from agents.refinement import RefinementAgent as RefinementLogic
from core.shared_memory import SharedMemory


class RefinementAgent(BaseAgent):

    def __init__(self, llm):
        super().__init__(llm)
        self.logic = RefinementLogic()

    def run(self, memory: SharedMemory):
        state = memory.get_full_state()

        sim = state.get("simulation_results")
        if sim:
            state["sim_metrics"] = sim

        state, report = self.logic.run(state)

        memory.write("sizing", state.get("sizing"))
        memory.write("refinement_report", report.__dict__)
        memory.write("status", state.get("status", DesignStatus.REFINEMENT_FAILED))

        return state, report
