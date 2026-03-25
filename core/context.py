# I13/core/context.py

class Context:

    def __init__(self):

        self.design_spec = None

        self.current_netlist = None

        self.simulation_result = None

        self.evaluation = None

        self.iteration = 0

        self.history = []

    def set(self, key, value):

        self.data[key] = value

    def get(self, key):

        return self.data.get(key)