import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from agents.sizing_agent import SizingAgent
from agents.topology_agent import TopologyAgent
from agents.simulation_agent import SimulationAgent
from core.reference_knowledge import ReferenceCatalog, yaml
from core.shared_memory import SharedMemory


class ReferenceCatalogTests(unittest.TestCase):
    def test_catalog_loads_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "notes.md").write_text(
                textwrap.dedent(
                    """\
                    Title: Demo Markdown Note
                    Schema: topology_note
                    Content-Type: topology_note
                    Topologies: adc_reference_buffer
                    Tags: adc, buffer
                    Summary: Markdown-backed reference note.

                    # Demo Markdown Note

                    Use a buffer when a converter reference must drive sampling capacitance.
                    """
                ),
                encoding="utf-8",
            )
            (root / "bundle.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "json-template",
                                "title": "JSON Template",
                                "schema": "adc_dac_driver_template",
                                "content_type": "template",
                                "topologies": ["adc_reference_buffer"],
                                "summary": "JSON-backed template entry.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            catalog = ReferenceCatalog.from_paths([str(root)])
            hits = catalog.search(query="adc reference buffer", topologies=["adc_reference_buffer"], limit=5)

            self.assertGreaterEqual(len(catalog.entries), 2)
            self.assertTrue(any(hit["content_type"] == "topology_note" for hit in hits))
            self.assertTrue(any(hit["content_type"] == "template" for hit in hits))

    def test_catalog_loads_yaml_when_available(self):
        if yaml is None:
            self.skipTest("PyYAML is not installed in this environment")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "bundle.yaml").write_text(
                textwrap.dedent(
                    """\
                    items:
                      - id: yaml-entry
                        title: YAML Evaluation Criteria
                        schema: evaluation_criteria
                        content_type: evaluation_criteria
                        topologies: [rc_lowpass]
                        summary: YAML-backed evaluation entry.
                    """
                ),
                encoding="utf-8",
            )
            catalog = ReferenceCatalog.from_paths([str(root)])
            hits = catalog.search(query="rc lowpass", topologies=["rc_lowpass"], content_types=["evaluation_criteria"])
            self.assertTrue(any(hit["id"] == "yaml-entry" for hit in hits))


class ReferenceDrivenAgentTests(unittest.TestCase):
    def test_topology_agent_can_pick_from_reference_catalog(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "topology.md").write_text(
                textwrap.dedent(
                    """\
                    Title: ADC Reference Buffer Note
                    Schema: topology_note
                    Content-Type: topology_note
                    Topologies: adc_reference_buffer
                    Tags: adc, reference, sampled_capacitor, buffering
                    Summary: Use this topology for ADC reference paths that must drive sampled capacitance.

                    # ADC Reference Buffer

                    Choose this topology when a converter reference needs a low-loading buffer.
                    """
                ),
                encoding="utf-8",
            )
            (root / "template.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "adc-reference-template",
                                "title": "ADC Reference Buffer Template",
                                "schema": "adc_dac_driver_template",
                                "content_type": "template",
                                "topologies": ["adc_reference_buffer"],
                                "summary": "Driver template for ADC reference buffering.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            catalog = ReferenceCatalog.from_paths([str(root)])

            memory = SharedMemory()
            memory.write(
                "specification",
                "Design an ADC reference path that can drive a sampled capacitor with low loading and stable buffering.",
            )
            memory.write("constraints", {"supply_v": 1.8})
            memory.write("case_metadata", {})

            agent = TopologyAgent(llm=None, reference_catalog=catalog)
            agent.run_agent(memory)

            self.assertEqual(memory.read("selected_topology"), "adc_reference_buffer")
            summary = memory.read("topology_reference_summary") or {}
            self.assertTrue(summary.get("used"))

    def test_sizing_agent_applies_reference_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "template.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "driver-template",
                                "title": "Driver Template",
                                "schema": "adc_dac_driver_template",
                                "content_type": "template",
                                "topologies": ["common_drain"],
                                "summary": "Provide a stronger default gm target.",
                                "data": {
                                    "default_constraints": {
                                        "target_gm_s": 0.003,
                                        "target_vov_v": 0.19,
                                    }
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            catalog = ReferenceCatalog.from_paths([str(root)])

            memory = SharedMemory()
            memory.write("selected_topology", "common_drain")
            memory.write("topology_plan", {"mode": "single", "stages": [{"topology": "common_drain"}]})
            memory.write("constraints", {"supply_v": 1.8})
            memory.write("case_metadata", {})

            agent = SizingAgent(reference_catalog=catalog)
            agent.run_agent(memory)

            sizing = memory.read("sizing") or {}
            summary = memory.read("sizing_reference_summary") or {}
            self.assertEqual(memory.read("status"), "sizing_complete")
            self.assertAlmostEqual(sizing.get("gm_target", 0.0), 0.003, places=6)
            self.assertIn("target_gm_s", summary.get("applied_defaults") or {})

    def test_simulation_agent_adds_reference_checks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "eval.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "eval-rc-reference",
                                "title": "RC Evaluation Reference",
                                "schema": "evaluation_criteria",
                                "content_type": "evaluation_criteria",
                                "topologies": ["rc_lowpass"],
                                "summary": "Adds a reference-driven cutoff check.",
                                "data": {
                                    "checks": [
                                        {
                                            "name": "reference_cutoff_alignment",
                                            "metric_key": "fc_hz",
                                            "target_constraint_key": "target_fc_hz",
                                            "kind": "target",
                                            "relative_tolerance": 0.1,
                                            "check_class": "target",
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            catalog = ReferenceCatalog.from_paths([str(root)])
            agent = SimulationAgent(reference_catalog=catalog)
            memory = SharedMemory()

            summary, ref_summary = agent._augment_verification_with_references(
                memory,
                topology="rc_lowpass",
                sizing={"R_ohm": 1000.0, "C_f": 1e-6},
                constraints={"target_fc_hz": 1000.0},
                sim={"fc_hz": 995.0},
                summary={
                    "target_checks": [],
                    "analytical_checks": [],
                    "passes": 0,
                    "fails": 0,
                    "unknown": 0,
                    "total_checks": 0,
                    "known_checks": 0,
                    "coverage_ratio": 0.0,
                    "overall_pass": True,
                },
            )

            self.assertTrue(ref_summary.get("used"))
            self.assertTrue(summary.get("reference_checks"))
            self.assertEqual(summary["reference_checks"][0]["status"], "pass")
            self.assertEqual(summary["passes"], 1)


if __name__ == "__main__":
    unittest.main()
