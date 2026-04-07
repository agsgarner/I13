# I13/agents/refinement_agent.py

from dataclasses import dataclass, field
from typing import Any, Dict, List

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from agents.refinement import RefinementAgent as RefinementLogic
from core.shared_memory import SharedMemory


@dataclass
class RefinementReport:
    changed: bool
    changes: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    next_action: str = "rerun_spice"


class RefinementAgent(BaseAgent):
    def __init__(self, llm=None, max_retries: int = 1, wait: float = 0):
        super().__init__(llm=llm, max_retries=max_retries, wait=wait)
        self.logic = RefinementLogic()

    def run_agent(self, memory: SharedMemory):
        state = memory.get_full_state()

        sim = state.get("simulation_results")
        if sim:
            state["sim_metrics"] = sim

        state, report = self.logic.run(state)

        memory.write("sizing", state.get("sizing"))
        memory.write("refinement_report", report.__dict__)
        memory.write("status", state.get("status", DesignStatus.REFINEMENT_FAILED))

        return state, report
