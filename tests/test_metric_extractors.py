import unittest

from core.metric_extractors import (
    extract_ac_metrics,
    extract_current_mirror_dc_metrics,
    extract_dc_metrics,
    extract_line_regulation_metrics,
    extract_noise_metrics_from_text,
    extract_transient_metrics,
)


class MetricExtractorTests(unittest.TestCase):
    def test_ac_metrics_extract_bandwidth_ugbw_and_phase_margin(self):
        ac_data = {
            "x": [1e3, 1e4, 1e5, 1e6, 1e7],
            "y": [10.0, 10.0, 7.07106781, 1.0, 0.1],
        }
        phase_data = {
            "x": [1e3, 1e4, 1e5, 1e6, 1e7],
            "y": [-10.0, -25.0, -55.0, -120.0, -170.0],
        }

        metrics = extract_ac_metrics(ac_data, input_ac_mag=1.0, phase_data=phase_data)

        self.assertAlmostEqual(metrics["gain_db"], 20.0, places=3)
        self.assertAlmostEqual(metrics["bandwidth_hz"], 1e5, delta=1e3)
        self.assertAlmostEqual(metrics["ugbw_hz"], 1e6, delta=1e4)
        self.assertAlmostEqual(metrics["phase_margin_deg"], 60.0, delta=1.0)

    def test_dc_metrics_extract_output_swing(self):
        dc_data = {
            "x": [0.0, 0.5, 1.0, 1.5],
            "y": [0.2, 0.45, 0.85, 1.05],
        }

        metrics = extract_dc_metrics(dc_data)

        self.assertAlmostEqual(metrics["sweep_span"], 1.5, places=6)
        self.assertAlmostEqual(metrics["output_swing_v"], 0.85, places=6)
        self.assertTrue(metrics["monotonic_non_decreasing"])

    def test_current_mirror_dc_metrics_extract_compliance_voltage(self):
        dc_data = {
            "x": [0.0, 0.1, 0.2, 0.3, 0.4],
            "y": [0.0, 40e-6, 82e-6, 97e-6, 100e-6],
        }

        metrics = extract_current_mirror_dc_metrics(dc_data, target_current_a=100e-6)

        self.assertAlmostEqual(metrics["compliance_voltage_v"], 0.3, places=6)
        self.assertAlmostEqual(metrics["iout_final_a"], 100e-6, places=12)

    def test_line_regulation_metrics_extract_slope(self):
        dc_data = {
            "x": [1.2, 1.5, 1.8],
            "y": [1.200, 1.201, 1.202],
        }

        metrics = extract_line_regulation_metrics(dc_data)

        self.assertAlmostEqual(metrics["line_regulation_mv_per_v"], 3.333333333333262, places=6)

    def test_transient_metrics_extract_settling_and_common_mode(self):
        tran_in = {
            "x": [0.0, 1e-9, 2e-9, 3e-9, 4e-9, 5e-9],
            "y": [0.0, 0.0, 0.2, 0.2, 0.2, 0.2],
        }
        tran_out = {
            "x": [0.0, 1e-9, 2e-9, 3e-9, 4e-9, 5e-9],
            "y": [0.0, 0.1, 0.8, 1.06, 1.03, 1.03],
        }
        tran_outn = {
            "x": [0.0, 1e-9, 2e-9, 3e-9, 4e-9, 5e-9],
            "y": [0.8, 0.8, 0.8, 0.8, 0.8, 0.8],
        }

        metrics = extract_transient_metrics(tran_out, tran_in_data=tran_in, tran_outn_data=tran_outn)

        self.assertAlmostEqual(metrics["output_swing_v"], 1.06, places=6)
        self.assertAlmostEqual(metrics["common_mode_final_v"], 0.915, places=6)
        self.assertAlmostEqual(metrics["differential_final_v"], 0.23, places=6)
        self.assertGreater(metrics["overshoot_pct"], 0.0)
        self.assertIn("settling_time_s", metrics)
        self.assertIn("max_slew_v_per_us", metrics)

    def test_noise_metrics_parse_totals_from_log(self):
        text = """
        Integrated noise results
        onoise_total = 1.23e-08
        inoise_total = 4.56e-12
        """

        metrics = extract_noise_metrics_from_text(text)

        self.assertAlmostEqual(metrics["onoise_total_vrms"], 1.23e-08)
        self.assertAlmostEqual(metrics["inoise_total_arms"], 4.56e-12)


if __name__ == "__main__":
    unittest.main()
