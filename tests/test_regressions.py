import unittest
import tempfile
import os
import math

from agents.topology_agent import TopologyAgent
from agents.op_point_agent import OpPointAgent
from agents.simulation_agent import SimulationAgent
from agents.refinement_agent import RefinementAgent
from core.demo_catalog import get_demo_profile, stable_demo_cases
from core.shared_memory import SharedMemory
from main import format_final_report, run_case, run_preflight


class TopologySelectionTests(unittest.TestCase):
    def _select(self, specification, constraints=None):
        memory = SharedMemory()
        memory.write("specification", specification)
        memory.write("constraints", constraints or {})
        agent = TopologyAgent(llm=None)
        agent.run_agent(memory)
        return memory.read("selected_topology")

    def test_selects_wilson_mirror(self):
        topology = self._select(
            "Design a Wilson current mirror for a 100 uA bias branch.",
            {"target_iout_a": 100e-6, "compliance_v": 0.9},
        )
        self.assertEqual(topology, "wilson_current_mirror")

    def test_selects_folded_cascode(self):
        topology = self._select(
            "Design a folded cascode op amp with 15 MHz unity-gain bandwidth.",
            {"target_ugbw_hz": 15e6, "target_gain_db": 62.0},
        )
        self.assertEqual(topology, "folded_cascode_opamp")

    def test_selects_comparator(self):
        topology = self._select(
            "Design a regenerative comparator for small-signal decision making.",
            {"input_overdrive_v": 20e-3, "supply_v": 1.8},
        )
        self.assertEqual(topology, "comparator")

    def test_selects_folded_cascode_for_low_noise_headroom_constrained_ota(self):
        topology = self._select(
            "Design a low noise fully differential OTA with CMFB for low headroom operation.",
            {
                "target_gain_db": 60.0,
                "target_ugbw_hz": 12e6,
                "low_noise_priority": True,
                "tight_headroom": True,
                "load_cap_f": 3e-12,
                "supply_v": 1.2,
            },
        )
        self.assertEqual(topology, "folded_cascode_opamp")


class DemoRegressionTests(unittest.TestCase):
    def _run_case(self, case_name):
        final_state = run_case(case_name)
        sim = final_state.get("simulation_results") or {}
        verification = sim.get("verification_summary") or {}
        self.assertEqual(final_state.get("status"), "design_validated")
        self.assertIsNotNone(sim.get("artifact_dir"))
        self.assertEqual(verification.get("fails", 0), 0)
        return final_state

    def test_rc_filter_case(self):
        final_state = self._run_case("rc")
        sim = final_state["simulation_results"]
        self.assertAlmostEqual(sim["fc_hz"], 1000.0, delta=100.0)

    def test_current_mirror_case(self):
        final_state = self._run_case("mirror")
        sim = final_state["simulation_results"]
        self.assertAlmostEqual(sim["iout_a"], 100e-6, delta=12e-6)

    def test_bandgap_case(self):
        final_state = self._run_case("bandgap_reference")
        sim = final_state["simulation_results"]
        self.assertAlmostEqual(sim["vref_v"], 1.2, delta=0.10)

    def test_comparator_case(self):
        final_state = self._run_case("comparator")
        sim = final_state["simulation_results"]
        self.assertTrue(sim.get("decision_correct"))
        self.assertLessEqual(sim.get("decision_delay_s", 1e9), 4e-9)

    def test_folded_cascode_case(self):
        final_state = self._run_case("folded_cascode_opamp")
        sim = final_state["simulation_results"]
        self.assertGreater(sim.get("gain_db", 0.0), 50.0)


class DemoProfileTests(unittest.TestCase):
    def test_ti_safe_profile_uses_curated_cases(self):
        profile = get_demo_profile("ti_safe")
        self.assertIn("opamp", profile)
        self.assertIn("bandgap_reference", profile)
        self.assertNotIn("wilson_mirror", profile)

    def test_ti_grand_demo_profile_includes_multi_stage_cases(self):
        profile = get_demo_profile("ti_grand_demo")
        self.assertIn("ti_filter_amp_chain", profile)
        self.assertIn("ti_three_stage_amp", profile)

    def test_stable_case_list_excludes_experimental_case(self):
        stable_cases = stable_demo_cases()
        self.assertIn("mirror", stable_cases)
        self.assertNotIn("wilson_mirror", stable_cases)

    def test_ti_safe_preflight_runs(self):
        run_preflight("ti_safe")


class OpParsingTests(unittest.TestCase):
    def test_builds_op_only_netlist(self):
        netlist = """* demo
R1 in out 1k
.control
set wr_singlescale
op
print @m1[gm]
ac dec 10 1 1e6
wrdata ac_out.csv frequency vm(out)
quit
.endc
.end
"""
        agent = OpPointAgent()
        op_only = agent._build_op_only_netlist(netlist)
        self.assertIn("\nop\n", op_only)
        self.assertIn("print @m1[gm]", op_only)
        self.assertNotIn("ac dec", op_only)
        self.assertNotIn("wrdata ac_out.csv", op_only)

    def test_extracts_device_metrics_from_log(self):
        payload = """
@m1[gm] = 1.25e-03
@m1[gds] = 2.50e-05
@m1[id] = 1.00e-04
@m1[vgs] = 7.20e-01
@m1[vds] = 4.00e-01
@mtail[id] = 2.00e-04
"""
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write(payload)
            path = handle.name
        try:
            agent = SimulationAgent()
            metrics = agent._extract_device_metrics_from_log(path)
        finally:
            os.unlink(path)

        self.assertAlmostEqual(metrics["m1"]["gm"], 1.25e-03)
        self.assertAlmostEqual(metrics["m1"]["gds"], 2.50e-05)
        self.assertAlmostEqual(metrics["m1"]["id"], 1.00e-04)
        self.assertAlmostEqual(metrics["m1"]["vgs"], 7.20e-01)
        self.assertAlmostEqual(metrics["m1"]["vds"], 4.00e-01)
        self.assertAlmostEqual(metrics["mtail"]["id"], 2.00e-04)

    def test_final_report_includes_spec_and_netlist_provenance(self):
        final_state = run_case("rc")
        report = format_final_report("rc", final_state)
        self.assertIn("Specification:", report)
        self.assertIn("Simulated netlist:", report)
        self.assertIn("Simulation provenance:", report)


class CharacterizationAndRefinementTests(unittest.TestCase):
    def test_gain_bw_uses_interpolation(self):
        agent = SimulationAgent()
        data = {
            "x": [1.0, 10.0, 100.0],
            "y": [10.0, 8.0, 5.0],
        }
        gain_db, bw_hz = agent._extract_gain_bw_from_ac(data, input_ac_mag=1.0)
        self.assertAlmostEqual(gain_db, 20.0 * math.log10(10.0), places=6)
        self.assertIsNotNone(bw_hz)
        self.assertAlmostEqual(bw_hz, 20.4, delta=1.0)

    def test_plot_validation_summary_counts_pass_fail(self):
        agent = SimulationAgent()
        summary = agent._summarize_plot_validations(
            [
                {"name": "ac_dataset", "status": "pass"},
                {"name": "tran_dataset", "status": "fail"},
                {"name": "ac_plot", "status": "pass"},
            ]
        )
        self.assertEqual(summary["passes"], 2)
        self.assertEqual(summary["fails"], 1)
        self.assertFalse(summary["overall_pass"])

    def test_wilson_mirror_op_resize_uses_m2_current(self):
        agent = OpPointAgent()
        sizing = {"W_out": 1.0e-6, "W_aux": 1.0e-6}
        constraints = {"target_iout_a": 100e-6}
        metrics = {"m2": {"id": 50e-6}}
        changed, _ = agent._resize_from_op(
            topology="wilson_current_mirror",
            sizing=sizing,
            constraints=constraints,
            metrics=metrics,
            op_log_text="",
        )
        self.assertTrue(changed)
        self.assertGreater(sizing["W_out"], 1.0e-6)
        self.assertNotEqual(sizing["W_aux"], 1.0e-6)

    def test_second_order_filter_refinement_adjusts_inductor(self):
        agent = RefinementAgent()
        state = {"sizing": {"L_h": 1e-3, "C_f": 1e-9, "R_ohm": 100.0, "q_target": 0.7}}
        constraints = {"target_fc_hz": 2000.0}
        sim = {"fc_hz": 3000.0, "q_factor": 0.7}
        new_state, report = agent._refine_second_order_filter(
            state=state,
            constraints=constraints,
            sizing=state["sizing"],
            sim=sim,
            mode="lowhigh",
        )
        self.assertTrue(report.changed)
        self.assertIn("L_h", report.changes)
        self.assertNotEqual(new_state["sizing"]["L_h"], 1e-3)


if __name__ == "__main__":
    unittest.main()
