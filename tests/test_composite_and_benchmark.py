import unittest

from agents.constraints_agent import ConstraintAgent
from agents.netlist_agent import NetlistAgent
from agents.sizing_agent import SizingAgent
from agents.topology_agent import TopologyAgent
from core.shared_memory import SharedMemory
from evaluation.benchmark_runner import _sample_record, pass_at_k
from llm.local_llm_stub import LocalLLMStub


class CompositePipelineTests(unittest.TestCase):
    def test_topology_agent_builds_composite_pipeline(self):
        memory = SharedMemory()
        memory.write(
            "specification",
            "Design a multi-stage amplifier with a gain stage followed by a buffer stage.",
        )
        memory.write(
            "constraints",
            {
                "supply_v": 1.8,
                "target_gain_db": 20.0,
                "target_bw_hz": 1e6,
                "power_limit_mw": 2.0,
            },
        )
        memory.write("case_metadata", {})

        agent = TopologyAgent(llm=LocalLLMStub())
        agent.run_agent(memory)

        self.assertEqual(memory.read("selected_topology"), "composite_pipeline")
        plan = memory.read("topology_plan") or {}
        self.assertEqual(plan.get("mode"), "composite")
        self.assertGreaterEqual(len(plan.get("stages") or []), 2)

    def test_topology_agent_applies_explicit_stage_constraints(self):
        memory = SharedMemory()
        memory.write("specification", "Design a cascaded three-stage amplifier.")
        memory.write(
            "constraints",
            {
                "supply_v": 1.8,
                "stage_topologies": ["common_source_res_load", "source_degenerated_cs", "common_drain"],
                "stage_constraints": [
                    {"target_gain_db": 14.0},
                    {"target_gain_db": 10.0, "target_bw_hz": 2.0e6},
                    {"target_gm_s": 2.5e-3},
                ],
            },
        )
        memory.write("case_metadata", {})

        TopologyAgent(llm=None).run_agent(memory)
        plan = memory.read("topology_plan") or {}
        stages = plan.get("stages") or []
        self.assertEqual(len(stages), 3)
        self.assertEqual(stages[0].get("constraints", {}).get("target_gain_db"), 14.0)
        self.assertEqual(stages[1].get("constraints", {}).get("target_bw_hz"), 2.0e6)
        self.assertEqual(stages[2].get("constraints", {}).get("target_gm_s"), 2.5e-3)

    def test_composite_pipeline_sizes_and_validates(self):
        memory = SharedMemory()
        memory.write("selected_topology", "composite_pipeline")
        memory.write(
            "topology_plan",
            {
                "mode": "composite",
                "stages": [
                    {"name": "stage1", "topology": "common_source_res_load", "role": "gain"},
                    {"name": "stage2", "topology": "common_drain", "role": "buffer"},
                ],
            },
        )
        memory.write(
            "constraints",
            {
                "supply_v": 1.8,
                "target_gain_db": 20.0,
                "target_bw_hz": 1e6,
                "power_limit_mw": 2.0,
                "target_gm_s": 2e-3,
            },
        )
        memory.write("case_metadata", {"simulation_plan": {"analyses": ["op", "ac", "tran"]}})

        sizing_agent = SizingAgent()
        sizing_agent.run_agent(memory)
        sizing = memory.read("sizing") or {}
        self.assertEqual(memory.read("status"), "sizing_complete")
        self.assertEqual(sizing.get("stage_count"), 2)

        constraint_agent = ConstraintAgent()
        constraint_agent.run_agent(memory)
        report = memory.read("constraints_report") or {}
        self.assertTrue(report.get("passed"))

        netlist_agent = NetlistAgent(llm=None)
        netlist_agent.run_agent(memory)
        netlist = memory.read("netlist") or ""
        self.assertEqual(memory.read("status"), "netlist_generated")
        self.assertIn(".control", netlist)
        self.assertIn("ac", netlist.lower())
        self.assertIn("tran", netlist.lower())
        self.assertIn("* STAGE idx=1", netlist)
        self.assertIn("* STAGE idx=2", netlist)
        stage_report = memory.read("netlist_stage_report") or {}
        self.assertTrue(stage_report.get("valid"))
        self.assertTrue(stage_report.get("stage_count_match"))


class BenchmarkMetricTests(unittest.TestCase):
    def test_pass_at_k(self):
        self.assertAlmostEqual(pass_at_k(10, 0, 1), 0.0)
        self.assertAlmostEqual(pass_at_k(10, 10, 5), 1.0)
        self.assertAlmostEqual(pass_at_k(5, 1, 1), 0.2)
        self.assertGreater(pass_at_k(10, 2, 5), pass_at_k(10, 2, 1))

    def test_sample_record_tracks_llm_and_composite_metrics(self):
        final_state = {
            "status": "design_validated",
            "selected_topology": "composite_pipeline",
            "selected_topologies": ["common_source_res_load", "common_drain"],
            "iteration": 0,
            "history": [
                {"event": "llm_call", "data": {"agent": "TopologyAgent", "task": "stage_plan", "ok": True}},
                {"event": "llm_call", "data": {"agent": "NetlistAgent", "task": "composite_netlist", "ok": False}},
            ],
            "simulation_results": {
                "verification_summary": {
                    "passes": 7,
                    "fails": 0,
                    "unknown": 1,
                    "known_checks": 7,
                    "total_checks": 8,
                    "coverage_ratio": 0.875,
                    "overall_pass": True,
                },
                "netlist_stage_report": {
                    "stage_count_match": True,
                    "topology_order_match": True,
                    "planned_stage_count": 2,
                    "realized_stage_count": 2,
                },
            },
        }
        record = _sample_record("demo_case", final_state, duration_s=1.23)
        self.assertTrue(record.get("success"))
        self.assertEqual(record.get("llm_call_count"), 2)
        self.assertEqual(record.get("llm_call_success_count"), 1)
        self.assertAlmostEqual(record.get("llm_call_success_rate"), 0.5)
        self.assertEqual(record.get("composite", {}).get("stage_count_match"), True)
        self.assertEqual(record.get("composite", {}).get("topology_order_match"), True)


if __name__ == "__main__":
    unittest.main()
