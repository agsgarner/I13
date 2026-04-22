import unittest

from core.demo_catalog import get_demo_case
from core.final_showcase import (
    FINAL_SHOWCASE_CASES,
    build_showcase_case_summary,
    render_showcase_case_markdown,
)
from main import run_case


class FinalShowcaseTests(unittest.TestCase):
    def test_showcase_cases_are_curated_and_stable(self):
        self.assertEqual(
            FINAL_SHOWCASE_CASES,
            ["rc", "mirror", "common_source", "folded_cascode_opamp", "bandgap_reference", "comparator"],
        )
        for case_name in FINAL_SHOWCASE_CASES:
            case = get_demo_case(case_name)
            self.assertEqual(case.get("readiness"), "stable")

    def test_showcase_case_markdown_has_required_sections(self):
        final_state = {
            "case_metadata": {"display_name": "Single-Stage RC Low-Pass Filter"},
            "specification": "Design a first-order low-pass filter with approximately 1 kHz cutoff.",
            "status": "design_validated",
            "selected_topology": "rc_lowpass",
            "selected_topologies": ["rc_lowpass"],
            "topology_reasoning": "Case metadata forced the demo topology.",
            "history": [
                {"event": "agent_executed", "data": {"agent": "TopologyAgent", "status": "topology_selected"}},
                {"event": "agent_executed", "data": {"agent": "SimulationAgent", "status": "simulation_complete"}},
            ],
            "sizing": {"R_ohm": 15915.0, "C_f": 1e-8},
            "simulation_results": {
                "artifact_dir": "artifacts/simulations/rc/demo",
                "intent": "Measure cutoff and transient settling.",
                "analyses": ["ac", "tran"],
                "ac_plot": "artifacts/simulations/rc/demo/ac_plot.svg",
                "tran_plot": "artifacts/simulations/rc/demo/tran_plot.svg",
                "verification_summary": {
                    "overall_verdict": "fully_verified",
                    "final_status": "pass",
                    "extracted_metrics": {"fc_hz": 1000.0},
                    "requirement_evaluations": [
                        {
                            "requirement": "fc_hz",
                            "requested": 1000.0,
                            "measured": 1000.0,
                            "status": "pass",
                            "assessment": "fully_verified",
                            "evidence": "ac_extractor",
                        }
                    ],
                },
            },
        }

        summary = build_showcase_case_summary("rc", final_state, mode="full")
        markdown = render_showcase_case_markdown(summary)

        self.assertIn("# Single-Stage RC Low-Pass Filter (rc)", markdown)
        self.assertIn("## Topology Choice", markdown)
        self.assertIn("## Sizing Snapshot", markdown)
        self.assertIn("### Extracted Metrics", markdown)
        self.assertIn("### Requirement Verdicts", markdown)
        self.assertIn("## Artifacts", markdown)

    def test_run_case_force_skip_simulation(self):
        final_state = run_case(
            "rc",
            runtime_options={
                "force_skip_simulation": True,
                "skip_simulation_reason": "Backup showcase test skip.",
            },
        )
        sim = final_state.get("simulation_results") or {}
        self.assertTrue(sim.get("simulation_skipped"))
        self.assertIn("Backup showcase test skip.", sim.get("skip_reason", ""))


if __name__ == "__main__":
    unittest.main()
