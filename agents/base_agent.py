# I13/agents/base_agent.py

from core.shared_memory import SharedMemory

class BaseAgent:
    """
    Base class for all agents.
    Provides shared LLM access.
    """

    def __init__(self, llm=None):
        self.llm = llm

    def run(self, memory: SharedMemory):
        raise NotImplementedError("Agent must implement run()")