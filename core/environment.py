# I13/core/environment.py

from core.context import Context

class Environment:

    def __init__(self):

        self.dataset = []

        self.trained_model = None

        self.simulator = None

        self.global_history = []

        self.constraints = {}
    
        self.context = Context()
        