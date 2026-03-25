# I13/agents/base_agent.py

from flow.pocketflow import Node
from core.shared_memory import SharedMemory


class BaseAgent(Node):
    """
    PocketFlow-native agent base class.
    Agents implement run_agent(memory).
    """

    def __init__(self, llm=None, max_retries=1, wait=0):
        super().__init__(max_retries=max_retries, wait=wait)
        self.llm = llm

    def prep(self, shared: SharedMemory):
        return shared

    def exec(self, memory: SharedMemory):
        return self.run_agent(memory)

    def post(self, shared: SharedMemory, prep_res, exec_res):
        shared.append_history(
            "agent_executed",
            {
                "agent": self.__class__.__name__,
                "status": shared.read("status")
            }
        )
        return shared.read("status")

    def run_agent(self, memory: SharedMemory):
        raise NotImplementedError("Agent must implement run_agent()")
    