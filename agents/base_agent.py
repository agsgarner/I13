# I13/agents/base_agent.py

class BaseAgent:
    """
    Base class for all agents.
    Provides shared LLM access.
    """

    def __init__(self, llm):
        self.llm = llm

    def run(self, memory):
        raise NotImplementedError