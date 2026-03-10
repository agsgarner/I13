# I13/agents/topology_agent.py

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory
from core.topology_library import TOPOLOGY_LIBRARY


class TopologyAgent(BaseAgent):
    """
    Uses LLM to select appropriate circuit topology
    based on user specifications.
    """

    def run(self, memory: SharedMemory):

        spec = memory.read("specification")

        if spec is None:
            memory.write("status", DesignStatus.NO_SPEC)
            return

        # Create prompt for local LLM
        prompt = f"""
        Select appropriate analog topology for:
        {spec}
        """

        result = self.llm.generate(prompt)
        
        topology = result["topology"]
        confidence = result["confidence"]

        if topology not in TOPOLOGY_LIBRARY:
            memory.write("status", DesignStatus.TOPOLOGY_UNKNOWN)
            memory.write("topology_confidence", confidence)
            memory.append_history("topology_unknown", topology)
            return

        memory.write("selected_topology", topology)
        memory.write("constraint_template", TOPOLOGY_LIBRARY[topology]["constraint_template"])
        memory.write("status", DesignStatus.TOPOLOGY_SELECTED)
        memory.write("topology_confidence", confidence)

        memory.append_history("topology_selected", topology)