# I13/agents/topology_agent.py

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory
from core.topology_library import TOPOLOGY_LIBRARY


class TopologyAgent(BaseAgent):
    def run_agent(self, memory: SharedMemory):
        spec = memory.read("specification")
        constraints = memory.read("constraints") or {}

        if not spec:
            memory.write("status", "topology_failed")
            memory.write("topology_error", "Missing specification")
            return None

        topology_keys = list(TOPOLOGY_LIBRARY.keys())

        prompt = f"""
You are selecting an analog circuit topology.

Available topology keys:
{topology_keys}

Specification:
{spec}

Constraints:
{constraints}

Choose the single best topology key.
Return JSON only in this exact schema:
{{
  "topology": "<one of the keys above>",
  "confidence": <float from 0 to 1>,
  "reasoning": "<brief explanation>"
}}
"""

        result = self.llm.generate(prompt)

        topology = result.get("topology")
        confidence = float(result.get("confidence", 0.0))
        reasoning = result.get("reasoning", "")

        if topology not in TOPOLOGY_LIBRARY:
            memory.write("status", "topology_failed")
            memory.write("topology_error", f"Invalid topology returned: {topology}")
            memory.write("topology_raw_response", result)
            return None

        memory.write("selected_topology", topology)
        memory.write("topology_metadata", TOPOLOGY_LIBRARY[topology])
        memory.write("topology_confidence", confidence)
        memory.write("topology_reasoning", reasoning)
        memory.write("status", "topology_selected")
        memory.append_history("topology_selected", topology)
        return result
    