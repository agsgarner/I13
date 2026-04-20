import json
import tempfile
import unittest
from pathlib import Path

from evaluation.report_export import export_comparison, normalize_framework_result


class ReportExportTests(unittest.TestCase):
    def test_normalize_framework_result(self):
        payload = {
            "overall": {
                "total_cases": 2,
                "total_samples": 10,
                "successful_samples": 7,
                "sample_success_rate": 0.7,
                "pass_at_k": {"k=1": 0.7, "k=3": 0.95},
                "avg_case_runtime_s": 12.5,
            },
            "case_summaries": [
                {
                    "case": "a",
                    "avg_iterations": 1.0,
                    "avg_verification_pass_rate": 0.9,
                    "avg_verification_coverage": 0.8,
                    "topology_match_rate": 1.0,
                },
                {
                    "case": "b",
                    "avg_iterations": 1.5,
                    "avg_verification_pass_rate": 0.8,
                    "avg_verification_coverage": 0.7,
                    "topology_match_rate": 0.5,
                },
            ],
            "samples": {
                "a": [{"llm_call_count": 3}, {"llm_call_count": 2}],
                "b": [{"llm_call_count": 1}],
            },
        }
        row = normalize_framework_result("ours", payload, ks=[1, 3, 5], source="dummy.json")
        self.assertEqual(row["framework"], "ours")
        self.assertAlmostEqual(row["sample_success_rate"], 0.7)
        self.assertAlmostEqual(row["pass_at_1"], 0.7)
        self.assertAlmostEqual(row["pass_at_3"], 0.95)
        self.assertIsNotNone(row["pass_at_5"])
        self.assertAlmostEqual(row["avg_case_iterations"], 1.25)
        self.assertAlmostEqual(row["avg_verification_pass_rate"], 0.85)
        self.assertAlmostEqual(row["avg_topology_match_rate"], 0.75)
        self.assertAlmostEqual(row["avg_llm_calls_per_sample"], 2.0)

    def test_export_comparison_writes_csv_and_tex(self):
        ours = {
            "overall": {
                "total_cases": 1,
                "total_samples": 5,
                "successful_samples": 4,
                "sample_success_rate": 0.8,
                "pass_at_k": {"k=1": 0.8, "k=3": 1.0},
                "avg_case_runtime_s": 5.0,
            },
            "case_summaries": [
                {
                    "case": "rc",
                    "num_samples": 5,
                    "successful_samples": 4,
                    "avg_iterations": 1.0,
                    "avg_verification_pass_rate": 0.9,
                    "avg_verification_coverage": 0.95,
                    "topology_match_rate": 1.0,
                }
            ],
            "samples": {"rc": [{"llm_call_count": 2}, {"llm_call_count": 1}]},
        }
        baseline = {
            "overall": {
                "total_cases": 1,
                "total_samples": 5,
                "successful_samples": 3,
                "sample_success_rate": 0.6,
                "avg_case_runtime_s": 4.0,
            },
            "case_summaries": [
                {
                    "case": "rc",
                    "num_samples": 5,
                    "successful_samples": 3,
                    "avg_iterations": 1.2,
                    "avg_verification_pass_rate": 0.8,
                    "avg_verification_coverage": 0.85,
                    "topology_match_rate": 0.6,
                }
            ],
            "samples": {"rc": [{"llm_call_count": 0}, {"llm_call_count": 0}]},
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            ours_path = tmp / "ours.json"
            baseline_path = tmp / "baseline.json"
            out_dir = tmp / "report"
            ours_path.write_text(json.dumps(ours))
            baseline_path.write_text(json.dumps(baseline))

            outputs = export_comparison(
                framework_specs=[
                    ("ours", str(ours_path)),
                    ("baseline", str(baseline_path)),
                ],
                out_dir=str(out_dir),
                ks=[1, 3],
                caption="Comparison",
                label="tab:test",
            )

            csv_path = Path(outputs["csv"])
            tex_path = Path(outputs["latex"])
            schema_path = Path(outputs["schema"])
            self.assertTrue(csv_path.exists())
            self.assertTrue(tex_path.exists())
            self.assertTrue(schema_path.exists())

            csv_text = csv_path.read_text()
            tex_text = tex_path.read_text()
            self.assertIn("framework", csv_text)
            self.assertIn("ours", csv_text)
            self.assertIn("baseline", csv_text)
            self.assertIn("pass_at_1", csv_text)
            self.assertIn("pass@1", tex_text)
            self.assertIn("\\begin{table*}", tex_text)


if __name__ == "__main__":
    unittest.main()
