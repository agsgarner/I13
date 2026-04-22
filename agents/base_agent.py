# I13/agents/base_agent.py

import os

from flow.pocketflow import Node
from core.shared_memory import SharedMemory
from core.reference_knowledge import load_reference_catalog


class BaseAgent(Node):
    """
    PocketFlow-native agent base class.
    Agents implement run_agent(memory).
    """

    def __init__(self, llm=None, reference_catalog=None, max_retries=1, wait=0):
        super().__init__(max_retries=max_retries, wait=wait)
        self.llm = llm
        self.reference_catalog = reference_catalog or load_reference_catalog()

    def prep(self, shared: SharedMemory):
        if os.getenv("I13_STAGE_OUTPUT", "1").strip() == "1":
            print(f"\n[Stage] {self.__class__.__name__}: starting")
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
        if os.getenv("I13_STAGE_OUTPUT", "1").strip() == "1":
            print(f"[Stage] {self.__class__.__name__}: {shared.read('status')}")
        return shared.read("status")

    def run_agent(self, memory: SharedMemory):
        raise NotImplementedError("Agent must implement run_agent()")

    def retrieve_references(
        self,
        memory: SharedMemory,
        *,
        query: str = "",
        topologies=None,
        schemas=None,
        content_types=None,
        vendor=None,
        limit: int = 5,
        trace_label: str = "reference_query",
    ):
        hits = self.reference_catalog.search(
            query=query,
            topologies=topologies,
            schemas=schemas,
            content_types=content_types,
            vendor=vendor,
            limit=limit,
        )
        memory.append_history(
            "reference_query",
            {
                "agent": self.__class__.__name__,
                "label": trace_label,
                "query": query,
                "topologies": list(topologies or []),
                "schemas": list(schemas or []),
                "content_types": list(content_types or []),
                "hit_count": len(hits),
                "hit_ids": [item.get("id") for item in hits],
            },
        )
        return hits
    
