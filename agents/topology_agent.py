# I13/agents/topology_agent.py

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory


class TopologyAgent(BaseAgent):
    """
    Uses LLM to select appropriate circuit topology
    based on user specifications.
    """

    def run(self, memory: SharedMemory):

        spec = memory.read("specification")

        if spec is None:
            memory.write("status", "no_specification")
            return

        # Create prompt for local LLM
        prompt = f"""
        Select appropriate analog topology for:
        {spec}
        """

        result = self.llm.generate(prompt)
        
        topology = result["topology"]
        confidence = result["confidence"]

        memory.write("selected_topology", topology)
        memory.write("status", "topology_selected")
        memory.write("topology_confidence", confidence)

        memory.append_history("topology_selected", topology)