# I13/flow/design_flow.py

from flow.pocketflow import Flow, Node


class FinalizeNode(Node):
    def post(self, shared, prep_res, exec_res):
        shared.write("status", "design_validated")
        return "done"


class FailNode(Node):
    def post(self, shared, prep_res, exec_res):
        if shared.read("status") != "design_invalid_after_retries":
            shared.write("status", "orchestration_failed")
        return "failed"


class RetryGateNode(Node):
    def prep(self, shared):
        return {"iteration": shared.read("iteration", 0)}

    def exec(self, prep_res):
        return prep_res["iteration"]

    def post(self, shared, prep_res, exec_res):
        max_iterations = self.params.get("max_iterations", 3)

        if exec_res + 1 >= max_iterations:
            shared.write("status", "design_invalid_after_retries")
            return "fail"

        shared.increment_iteration()
        return "retry"


def build_design_flow(
    topology_agent,
    sizing_agent,
    constraint_agent,
    netlist_agent,
    simulation_agent,
    refinement_agent,
    max_iterations=3,
):
    finalize = FinalizeNode()
    fail = FailNode()
    retry_gate = RetryGateNode()

    flow = Flow(start=topology_agent)
    flow.set_params({"max_iterations": max_iterations})

    topology_agent - "topology_selected" >> sizing_agent
    topology_agent - "topology_failed" >> fail

    sizing_agent - "sizing_complete" >> constraint_agent
    sizing_agent - "sizing_failed" >> fail

    constraint_agent - "constraints_ok" >> netlist_agent
    constraint_agent - "constraints_failed" >> fail

    netlist_agent - "netlist_generated" >> simulation_agent
    netlist_agent - "netlist_failed" >> fail

    simulation_agent - "simulation_complete" >> refinement_agent
    simulation_agent - "simulation_failed" >> fail

    refinement_agent - "refined" >> retry_gate
    refinement_agent - "refinement_no_change" >> finalize
    refinement_agent - "refinement_skipped" >> finalize
    refinement_agent - "refinement_failed" >> fail

    retry_gate - "retry" >> constraint_agent
    retry_gate - "fail" >> fail

    return flow
