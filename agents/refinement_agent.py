# I13/agents/refinement_agent.py

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

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
    def __init__(
        self,
        llm=None,
        max_step_up: float = 1.5,
        max_step_down: float = 0.7,
        min_factor: float = 0.2,
        max_factor: float = 5.0,
        max_retries: int = 1,
        wait: float = 0,
    ):
        super().__init__(llm=llm, max_retries=max_retries, wait=wait)
        self.max_step_up = max_step_up
        self.max_step_down = max_step_down
        self.min_factor = min_factor
        self.max_factor = max_factor

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
