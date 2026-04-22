# I13/flow/design_flow.py

from agents.design_status import DesignStatus
from flow.pocketflow import Flow, Node


class FinalizeNode(Node):
    def post(self, shared, prep_res, exec_res):
        sim = shared.read("simulation_results") or {}
        verification = sim.get("verification_summary") or {}
        if verification.get("final_status") == "pass":
            shared.write("status", DesignStatus.DESIGN_VALIDATED)
        else:
            shared.write("status", DesignStatus.DESIGN_INVALID)
        return "done"


class FailNode(Node):
    def post(self, shared, prep_res, exec_res):
        if shared.read("status") != DesignStatus.DESIGN_INVALID_AFTER_RETRIES:
            shared.write("status", DesignStatus.ORCHESTRATION_FAILED)
        return "failed"


class RetryGateNode(Node):
    def prep(self, shared):
        return {"iteration": shared.read("iteration", 0)}

    def exec(self, prep_res):
        return prep_res["iteration"]

    def post(self, shared, prep_res, exec_res):
        max_iterations = self.params.get("max_iterations", 3)

        if exec_res + 1 >= max_iterations:
            shared.write("status", DesignStatus.DESIGN_INVALID_AFTER_RETRIES)
            return "fail"

        shared.increment_iteration()
        return "retry"


def build_design_flow(
    topology_agent,
    sizing_agent,
    constraint_agent,
    netlist_agent,
    op_point_agent,
    simulation_agent,
    refinement_agent,
    max_iterations=3,
):
    finalize = FinalizeNode()
    fail = FailNode()
    retry_gate = RetryGateNode()

    flow = Flow(start=topology_agent)
    flow.set_params({"max_iterations": max_iterations})

    topology_agent - DesignStatus.TOPOLOGY_SELECTED >> sizing_agent
    topology_agent - DesignStatus.TOPOLOGY_FAILED >> fail

    sizing_agent - DesignStatus.SIZING_COMPLETE >> constraint_agent
    sizing_agent - DesignStatus.SIZING_FAILED >> fail

    constraint_agent - DesignStatus.CONSTRAINTS_OK >> netlist_agent
    constraint_agent - DesignStatus.CONSTRAINTS_FAILED >> fail

    netlist_agent - DesignStatus.NETLIST_GENERATED >> op_point_agent
    netlist_agent - DesignStatus.NETLIST_FAILED >> fail

    op_point_agent - DesignStatus.OP_SIZING_COMPLETE >> simulation_agent
    op_point_agent - DesignStatus.OP_SIZING_REFINED >> constraint_agent
    op_point_agent - DesignStatus.OP_SIZING_FAILED >> fail

    simulation_agent - DesignStatus.SIMULATION_COMPLETE >> refinement_agent
    simulation_agent - DesignStatus.SIMULATION_FAILED >> fail

    refinement_agent - DesignStatus.REFINED >> retry_gate
    refinement_agent - DesignStatus.REFINEMENT_NO_CHANGE >> finalize
    refinement_agent - DesignStatus.REFINEMENT_SKIPPED >> finalize
    refinement_agent - DesignStatus.REFINEMENT_FAILED >> fail

    retry_gate - "retry" >> constraint_agent
    retry_gate - "fail" >> fail

    return flow
