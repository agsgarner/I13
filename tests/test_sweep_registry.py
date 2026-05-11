import unittest

from core.demo_catalog import READINESS_STABLE_DEMO, get_demo_case, stable_demo_cases
from core.sweep_registry import (
    CASE_SWEEP_SCHEMAS,
    evaluate_sweep_outcome,
    get_case_sweep_schema,
    list_ui_cases,
    sweepable_parameters,
)


class SweepRegistryTests(unittest.TestCase):
    def test_sweep_schema_case_keys_exist(self):
        for case_key in CASE_SWEEP_SCHEMAS:
            case = get_demo_case(case_key)
            self.assertEqual(case.get("case_key"), case_key)

    def test_sweep_schema_parameters_declared(self):
        for case_key in CASE_SWEEP_SCHEMAS:
            params = sweepable_parameters(case_key)
            self.assertGreaterEqual(len(params), 1, msg=f"{case_key} has no sweep parameters")

    def test_stable_demo_cases_have_schema(self):
        for case_key in stable_demo_cases():
            schema = get_case_sweep_schema(case_key)
            self.assertTrue(schema, msg=f"{case_key} is stable_demo but has no sweep schema")
            self.assertEqual(schema.get("readiness"), READINESS_STABLE_DEMO)

    def test_sponsor_ui_catalog_hides_non_demo_cases(self):
        visible = {item["key"] for item in list_ui_cases(include_experimental=False, sponsor_demo_only=True)}
        self.assertIn("rc", visible)
        self.assertNotIn("diff_pair", visible)

    def test_evaluate_sweep_outcome_flags_missing_artifacts(self):
        final_state = {
            "status": "design_validated",
            "simulation_results": {
                "verification_summary": {
                    "final_status": "pass",
                    "overall_verdict": "fully_verified",
                    "requirement_evaluations": [
                        {"requirement": "fc_hz", "status": "pass"},
                    ],
                }
            },
        }
        outcome = evaluate_sweep_outcome(
            final_state,
            case_name="rc",
            sweep_param="target_fc_hz",
            row={
                "generated_netlist": "",
                "final_report": "",
                "schematic_png": "",
                "ac_plot": "",
                "tran_plot": "",
            },
        )
        self.assertEqual(outcome.get("status"), "ARTIFACT MISSING")
        self.assertIn("generated_netlist", outcome.get("missing_artifacts"))


if __name__ == "__main__":
    unittest.main()
