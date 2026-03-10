# SharedMemory.c
# I13/core

from datetime import datetime


class SharedMemory:
    def __init__(self):
        self.state = {
            "specification": None,
            "selected_topology": None,
            "topology_confidence": None,
            "constraint_template": None,
            "constraints": None,
            "sizing": None,
            "sizing_report": None,
            "netlist": None,
            "constraints_report": None,
            "simulation_data": None,
            "simulation_results": None,
            "refinement_report": None,
            "status": "initialized",
            "history": []
        }

    def write(self, key, value):
        self.state[key] = value
        self.append_history("write", {key: value})

    def read(self, key):
        return self.state.get(key)

    def append_history(self, event, data):
        self.state["history"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "event": event,
            "data": data
        })

    def get_full_state(self):
        return self.state

    def load_state(self, data, overwrite=True):
        if not isinstance(data, dict):
            raise ValueError("State must be a dict")
        for key, value in data.items():
            if overwrite or key not in self.state:
                self.state[key] = value