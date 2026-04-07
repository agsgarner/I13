#I13/core/design_status.py

class DesignStatus:
    INITIALIZED = "initialized"
    NO_SPEC = "no_specification"
    TOPOLOGY_UNKNOWN = "topology_unknown"
    TOPOLOGY_SELECTED = "topology_selected"
    TOPOLOGY_FAILED = "topology_failed"

    SIZING_COMPLETE = "sizing_complete"
    SIZING_FAILED = "sizing_failed"

    CONSTRAINTS_OK = "constraints_ok"
    CONSTRAINTS_FAILED = "constraints_failed"

    NETLIST_GENERATED = "netlist_generated"
    NETLIST_FAILED = "netlist_failed"

    SIMULATION_COMPLETE = "simulation_complete"
    SIMULATION_FAILED = "simulation_failed"
    REFINED = "refined"
    REFINEMENT_NO_CHANGE = "refinement_no_change"
    REFINEMENT_SKIPPED = "refinement_skipped"
    REFINEMENT_FAILED = "refinement_failed"
    DESIGN_VALIDATED = "design_validated"
    DESIGN_INVALID = "design_invalid"
    DESIGN_INVALID_AFTER_RETRIES = "design_invalid_after_retries"
    ORCHESTRATION_FAILED = "orchestration_failed"
