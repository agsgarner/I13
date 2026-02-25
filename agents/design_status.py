#I13/core/design_status.py

class DesignStatus:
    INITIALIZED = "initialized"
    NO_SPEC = "no_specification"
    TOPOLOGY_SELECTED = "topology_selected"
    SIZING_COMPLETE = "sizing_complete"
    SIZING_FAILED = "sizing_failed"
    CONSTRAINTS_OK = "constraints_ok"
    CONSTRAINTS_FAILED = "constraints_failed"
    SIMULATION_COMPLETE = "simulation_complete"
    SIMULATION_FAILED = "simulation_failed"
    DESIGN_VALIDATED = "design_validated"
    DESIGN_INVALID = "design_invalid"
    DESIGN_INVALID_AFTER_RETRIES = "design_invalid_after_retries"
    ORCHESTRATION_FAILED = "orchestration_failed"