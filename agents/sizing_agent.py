# agents/sizing_agent.py

from agents.base_agent import BaseAgent

class SizingAgent(BaseAgent):
    """
    Deterministic first-order sizing calculations.
    """

    def run(self, memory):

        topology = memory.read("selected_topology")
        constraints = memory.read("constraints")

        if constraints is None:
            memory.write("status", "sizing_failed")
            return

        if topology == "rc_lowpass":
            fc = constraints.get("target_fc_hz")
            if fc is None or fc <= 0:
                memory.write("status", "sizing_failed")
                return

            C = 1e-9
            R = 1 / (2 * 3.141592653589793 * fc * C)

            sizing = {
                "R_ohm": R,
                "C_f": C
            }

            memory.write("sizing", sizing)
            memory.write("status", "sizing_complete")
            return

        # Fallback for unimplemented topologies
        memory.write("status", "sizing_failed")