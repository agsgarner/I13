# I13/core/shared_memory.py

from datetime import datetime
from copy import deepcopy
from agents.design_status import DesignStatus


class SharedMemory:
    def __init__(self):
        self.state = {
            "specification": None,
            "selected_topology": None,
            "topology_metadata": None,
            "constraints": None,
            "sizing": None,
            "netlist": None,
            "simulation_results": None,
            "constraints_report": None,
            "sizing_report": None,
            "refinement_report": None,
            "topology_confidence": None,
            "status": DesignStatus.INITIALIZED,
            "iteration": 0,
            "history": []
        }

    def write(self, key, value):
        self.state[key] = value
        self.append_history("write", {key: deepcopy(value)})

    def read(self, key, default=None):
        return self.state.get(key, default)

    def update(self, data: dict):
        for key, value in data.items():
            self.write(key, value)

    def append_history(self, event, data):
        self.state["history"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "event": event,
            "data": deepcopy(data)
        })

    def increment_iteration(self):
        self.state["iteration"] += 1
        self.append_history("iteration_incremented", self.state["iteration"])

    def get_full_state(self):
        return deepcopy(self.state)

    def get_recent_history(self, count=10):
        count = max(0, int(count))
        return deepcopy(self.state["history"][-count:])
    
