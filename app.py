import streamlit as st

from core.shared_memory import SharedMemory
from llm.local_llm_stub import LocalLLMStub

from agents.topology_agent import TopologyAgent
from agents.sizing_agent import SizingAgent
from agents.constraints_agent import ConstraintAgent
from agents.simulation_agent import SimulationAgent
from agents.refinement_agent import RefinementAgent
from agents.orchestration_agent import OrchestrationAgent


def run_design_pipeline(specification: str, target_fc_hz: float):
    """
    Runs the existing multi-agent pipeline with the given
    specification and cutoff frequency, and returns the final state.
    """
    memory = SharedMemory()

    memory.write("specification", specification)
    memory.write(
        "constraints",
        {
            "circuit_type": "rc_lowpass",
            "target_fc_hz": target_fc_hz,
        },
    )

    llm = LocalLLMStub()

    topology_agent = TopologyAgent(llm)
    sizing_agent = SizingAgent()
    constraint_agent = ConstraintAgent()
    simulation_agent = SimulationAgent()
    refinement_agent = RefinementAgent(llm)

    orchestrator = OrchestrationAgent(
        memory,
        topology_agent,
        sizing_agent,
        constraint_agent,
        simulation_agent,
        refinement_agent,
    )

    return orchestrator.run()


def main():
    st.title("Multi-Agent Analog Filter Design (Demo)")
    st.write(
        "This UI runs the existing multi-agent pipeline using the local LLM stub "
        "and analytic formulas (no SPICE yet)."
    )

    with st.form("design_form"):
        spec = st.text_input(
            "Design specification",
            value="Design a lowpass filter with 1 kHz cutoff",
        )
        target_fc = st.number_input(
            "Target cutoff frequency (Hz)",
            min_value=1.0,
            value=1000.0,
            step=100.0,
        )

        submitted = st.form_submit_button("Run design")

    if submitted:
        with st.spinner("Running multi-agent design pipeline..."):
            state = run_design_pipeline(spec, target_fc)

        st.subheader("Specification")
        st.write(state.get("specification"))

        st.subheader("Topology Selection")
        st.write(
            {
                "selected_topology": state.get("selected_topology"),
                "topology_confidence": state.get("topology_confidence"),
            }
        )

        st.subheader("Sizing Parameters")
        st.json(state.get("sizing", {}))

        st.subheader("Constraint Evaluation")
        constraints_report = state.get("constraints_report", {})
        st.write(
            {
                "passed": constraints_report.get("passed"),
                "completeness_score": constraints_report.get("completeness_score"),
            }
        )
        if constraints_report.get("issues"):
            st.markdown("**Issues**")
            for issue in constraints_report.get("issues", []):
                st.write(f"- {issue}")

        if constraints_report.get("warnings"):
            st.markdown("**Warnings**")
            for w in constraints_report.get("warnings", []):
                st.write(f"- {w}")

        st.subheader("Simulation Results")
        st.json(state.get("simulation_results", {}))

        st.subheader("Refinement Report")
        st.json(state.get("refinement_report", {}))

        st.subheader("Final System Status")
        st.write(state.get("status"))

        with st.expander("Execution history (last 10 events)"):
            history = state.get("history", [])
            for event in history[-10:]:
                st.write(event)


if __name__ == "__main__":
    main()

