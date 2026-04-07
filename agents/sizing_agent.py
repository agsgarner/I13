# I13/agents/sizing_agent.py

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory


@dataclass
class SizingReport:
    success: bool
    notes: list = field(default_factory=list)


class SizingAgent(BaseAgent):

    def __init__(self):
        super().__init__()
        self.logic = SizingLogic()

    def run(self, memory: SharedMemory):
        state = memory.get_full_state()
        state, report = self.logic.run(state)

        memory.write("sizing", state.get("sizing"))
        memory.write("sizing_report", report.__dict__)
        memory.write("status", DesignStatus.SIZING_COMPLETE)
        return state

        if report.success:
            memory.write("status", DesignStatus.SIZING_COMPLETE)
        else:
            memory.write("status", DesignStatus.SIZING_FAILED)

        return state, report