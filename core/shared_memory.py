# SharedMemory.c
# I13/core

from datetime import datetime


class SharedMemory:
    def __init__(self):
        self.state = {
            "specification": None,
            "selected_topology": None,
            "constraints": None,
            "sizing": None,
            "netlist": None,
            "constraints_report": None,
            "simulation_data": None,
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