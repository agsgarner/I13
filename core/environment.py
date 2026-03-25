# I13/core/environment.py

class Environment:

    def __init__(self):

        self.dataset = []

        self.trained_model = None

        self.simulator = None

        self.global_history = []

        self.constraints = {}
    
        self.context = Context()