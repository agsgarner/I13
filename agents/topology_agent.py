# I13/agents/topology_agent.py

import re

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory
from core.topology_library import TOPOLOGY_LIBRARY
from core.analog_defaults import ANALOG_DEFAULTS


class TopologyAgent(BaseAgent):
    MULTI_STAGE_HINTS = (
        "multi-stage",
        "multistage",
        "two-stage",
        "three-stage",
        "cascade",
        "cascaded",
        "preamp",
        "driver stage",
    )

    def run_agent(self, memory: SharedMemory):
        spec_text = (memory.read("specification") or "").strip()
        spec = spec_text.lower()
        constraints = self._merged_defaults(memory.read("constraints") or {})
        case_meta = memory.read("case_metadata") or {}

        if not spec_text:
            memory.write("status", DesignStatus.TOPOLOGY_FAILED)
            memory.write("topology_error", "Missing specification")
            return None

        topology = None
        confidence = 0.0
        reasoning = ""

        forced_topology = case_meta.get("forced_topology") or constraints.get("forced_topology")
        if forced_topology in TOPOLOGY_LIBRARY:
            topology = forced_topology
            confidence = 0.99
            reasoning = "Case metadata forced the demo topology."
        else:
            rule_result = self._rule_based_topology(spec, constraints)
            if rule_result is not None:
                topology, confidence, reasoning = rule_result
            else:
                llm_result = self._llm_topology(spec, constraints, memory=memory)
                if llm_result is not None:
                    topology, confidence, reasoning = llm_result

        # deterministic fallback so the flow never dies on a missing topology
        if topology not in TOPOLOGY_LIBRARY:
            fallback = self._deterministic_fallback(constraints, spec)
            topology, confidence, reasoning = fallback

        stage_plan = self._build_stage_plan(
            spec_text=spec_text,
            constraints=constraints,
            base_topology=topology,
            forced_topology=forced_topology,
            memory=memory,
        )
        if (stage_plan.get("mode") == "composite") and stage_plan.get("stages"):
            topology = "composite_pipeline"
            confidence = max(confidence, float(stage_plan.get("confidence", 0.75)))
            stage_summary = " -> ".join(item.get("topology", "?") for item in stage_plan["stages"])
            reasoning = (
                f"{reasoning} "
                f"Expanded to composite pipeline with {len(stage_plan['stages'])} stages: {stage_summary}."
            ).strip()

        if topology not in TOPOLOGY_LIBRARY:
            memory.write("status", DesignStatus.TOPOLOGY_FAILED)
            memory.write("topology_error", f"Invalid topology returned: {topology}")
            memory.write("topology_raw_response", {"topology": topology})
            return None

        selected_topologies = [item.get("topology") for item in stage_plan.get("stages", []) if item.get("topology")]
        if not selected_topologies:
            selected_topologies = [topology]

        memory.write("selected_topology", topology)
        memory.write("selected_topologies", selected_topologies)
        memory.write("topology_plan", stage_plan)
        memory.write("topology_metadata", TOPOLOGY_LIBRARY[topology])
        memory.write("topology_confidence", confidence)
        memory.write("topology_reasoning", reasoning)
        memory.write("status", DesignStatus.TOPOLOGY_SELECTED)
        memory.append_history(
            "topology_selected",
            {
                "topology": topology,
                "selected_topologies": selected_topologies,
                "plan_mode": stage_plan.get("mode"),
            },
        )

        return {
            "topology": topology,
            "selected_topologies": selected_topologies,
            "topology_plan": stage_plan,
            "confidence": confidence,
            "reasoning": reasoning,
        }

    def _build_stage_plan(
        self,
        spec_text: str,
        constraints: dict,
        base_topology: str,
        forced_topology: str,
        memory: SharedMemory,
    ):
        explicit_list = constraints.get("stage_topologies")
        if isinstance(explicit_list, (list, tuple)):
            stage_keys = [key for key in explicit_list if key in TOPOLOGY_LIBRARY and key != "composite_pipeline"]
            if stage_keys:
                raw_stage_constraints = constraints.get("stage_constraints")

                def stage_constraints_for(index: int, stage_key: str):
                    if isinstance(raw_stage_constraints, list):
                        if index < len(raw_stage_constraints) and isinstance(raw_stage_constraints[index], dict):
                            return dict(raw_stage_constraints[index])
                        return {}

                    if isinstance(raw_stage_constraints, dict):
                        stage_name = f"stage{index + 1}"
                        for lookup in (stage_name, str(index), stage_key):
                            payload = raw_stage_constraints.get(lookup)
                            if isinstance(payload, dict):
                                return dict(payload)
                    return {}

                mode = "composite" if len(stage_keys) > 1 else "single"
                return {
                    "mode": mode,
                    "source": "constraints",
                    "confidence": 0.99 if mode == "composite" else 0.90,
                    "stages": [
                        {
                            "name": f"stage{i + 1}",
                            "topology": key,
                            "role": f"stage_{i + 1}",
                            "constraints": stage_constraints_for(i, key),
                        }
                        for i, key in enumerate(stage_keys)
                    ],
                }

        if forced_topology and forced_topology != "composite_pipeline":
            return {
                "mode": "single",
                "source": "forced_topology",
                "confidence": 0.99,
                "stages": [{"name": "stage1", "topology": base_topology, "role": "primary"}],
            }

        spec = spec_text.lower()
        if not self._suggests_multi_stage(spec, constraints):
            return {
                "mode": "single",
                "source": "single_stage",
                "confidence": 0.90,
                "stages": [{"name": "stage1", "topology": base_topology, "role": "primary"}],
            }

        if base_topology in {"two_stage_miller", "folded_cascode_opamp"}:
            return {
                "mode": "single",
                "source": "intrinsic_multi_stage_topology",
                "confidence": 0.88,
                "stages": [{"name": "stage1", "topology": base_topology, "role": "primary"}],
            }

        max_stage_count = max(2, int(constraints.get("max_stage_count", 4)))
        if self.llm is not None and bool(constraints.get("enable_llm_stage_planning", True)):
            llm_plan = self._llm_stage_plan(spec_text, constraints, max_stage_count=max_stage_count, memory=memory)
            if llm_plan is not None:
                return llm_plan

        stage_count = min(max_stage_count, self._infer_stage_count(spec, default_count=2))
        stage_topologies = [base_topology]
        while len(stage_topologies) < stage_count:
            stage_topologies.append(self._default_followup_stage(stage_topologies[-1]))
        return {
            "mode": "composite" if len(stage_topologies) > 1 else "single",
            "source": "deterministic_multi_stage_fallback",
            "confidence": 0.65,
            "stages": [
                {"name": f"stage{i + 1}", "topology": key, "role": f"stage_{i + 1}"}
                for i, key in enumerate(stage_topologies)
            ],
        }

    def _suggests_multi_stage(self, spec: str, constraints: dict):
        if isinstance(constraints.get("stage_topologies"), (list, tuple)) and len(constraints.get("stage_topologies")) > 1:
            return True
        if constraints.get("stage_count") is not None:
            try:
                if int(constraints.get("stage_count")) > 1:
                    return True
            except Exception:
                pass
        return any(hint in spec for hint in self.MULTI_STAGE_HINTS) or ("stage" in spec and "single-stage" not in spec)

    def _infer_stage_count(self, spec: str, default_count: int):
        match = re.search(r"\b(\d+)\s*[- ]*stage\b", spec)
        if match:
            try:
                return max(1, int(match.group(1)))
            except Exception:
                pass
        if "two-stage" in spec or "2-stage" in spec:
            return 2
        if "three-stage" in spec or "3-stage" in spec:
            return 3
        return default_count

    def _default_followup_stage(self, previous_topology: str):
        category = (TOPOLOGY_LIBRARY.get(previous_topology) or {}).get("category")
        if category in {"opamp", "amplifier"}:
            return "common_drain"
        if category == "filter":
            return previous_topology
        return "common_source_res_load"

    def _rule_based_topology(self, spec: str, constraints: dict):
        high_gain_requested = float(constraints.get("target_gain_db", 0.0) or 0.0) >= 45.0
        heavy_cap_load = float(constraints.get("load_cap_f", 0.0) or 0.0) >= 2e-12
        low_power_bias = float(constraints.get("power_limit_mw", 1e9) or 1e9) <= 1.0
        low_noise_hint = (
            "low noise" in spec
            or "noise" in spec
            or bool(constraints.get("low_noise_priority"))
            or constraints.get("input_referred_noise_nv_per_rtHz") is not None
        )
        tight_headroom_hint = (
            "low voltage" in spec
            or "low headroom" in spec
            or bool(constraints.get("tight_headroom"))
            or float(constraints.get("supply_v", 1.8) or 1.8) <= 1.2
        )

        conf, reasons = self._score_match([
            (
                "band-pass" in spec
                or "band pass" in spec
                or constraints.get("target_center_hz") is not None,
                0.50,
                "band-pass wording or center-frequency target",
            ),
            (constraints.get("target_bw_hz") is not None, 0.20, "target_bw_hz present"),
            ("rlc" in spec, 0.15, "rlc wording"),
        ])
        if conf >= 0.50:
            return ("rlc_bandpass_2nd_order", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            (
                "high-pass" in spec
                or "high pass" in spec
                or "ac-coupled" in spec
                or "ac coupled" in spec,
                0.45,
                "high-pass wording",
            ),
            ("rlc" in spec, 0.15, "rlc wording"),
            (constraints.get("target_fc_hz") is not None, 0.15, "target_fc_hz present"),
        ])
        if conf >= 0.50:
            return ("rlc_highpass_2nd_order", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            (
                "butterworth" in spec
                or "bessel" in spec
                or "chebyshev" in spec
                or constraints.get("response_family") is not None,
                0.35,
                "filter response-family wording",
            ),
            ("low-pass" in spec or "low pass" in spec or "filter" in spec, 0.45, "filter wording"),
            ("cutoff" in spec, 0.20, "cutoff wording"),
            (constraints.get("target_fc_hz") is not None, 0.20, "target_fc_hz present"),
            ("rlc" in spec, 0.15, "rlc wording"),
        ])
        if conf >= 0.50:
            if "rlc" in spec or constraints.get("response_family") is not None:
                return ("rlc_lowpass_2nd_order", conf, f"Matched by: {', '.join(reasons)}")
            return ("rc_lowpass", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("current mirror" in spec or "bias current" in spec or "copy current" in spec, 0.45, "current mirror wording"),
            (constraints.get("target_iout_a") is not None, 0.20, "target_iout_a present"),
        ])
        if conf >= 0.50:
            if "widlar" in spec:
                return ("widlar_current_mirror", conf, f"Matched by: {', '.join(reasons)}")
            if "wilson" in spec:
                return ("wilson_current_mirror", conf, f"Matched by: {', '.join(reasons)}")
            if "cascode" in spec:
                return ("cascode_current_mirror", conf, f"Matched by: {', '.join(reasons)}")
            return ("current_mirror", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("differential pair" in spec or "diff pair" in spec or "differential front-end" in spec, 0.45, "differential wording"),
        ])
        if conf >= 0.45:
            return ("diff_pair", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("source follower" in spec or "common-drain" in spec or "common drain" in spec, 0.55, "source follower wording"),
        ])
        if conf >= 0.50:
            return ("common_drain", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("common-gate" in spec or "common gate" in spec, 0.55, "common-gate wording"),
        ])
        if conf >= 0.50:
            return ("common_gate", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("source-degenerated" in spec or "source degenerated" in spec, 0.55, "source degeneration wording"),
        ])
        if conf >= 0.50:
            return ("source_degenerated_cs", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("active load" in spec, 0.55, "active-load wording"),
        ])
        if conf >= 0.50:
            return ("common_source_active_load", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            (low_noise_hint, 0.25, "low-noise intent"),
            (tight_headroom_hint, 0.20, "tight-headroom intent"),
            (high_gain_requested, 0.20, "high-gain target"),
            (heavy_cap_load, 0.10, "heavy capacitive load"),
            (
                "fully differential" in spec
                or "fully-differential" in spec
                or "cmfb" in spec
                or "differential op amp" in spec,
                0.35,
                "differential OTA wording",
            ),
        ])
        if conf >= 0.50:
            return ("folded_cascode_opamp", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            (
                "folded cascode" in spec
                or "folded-cascode" in spec,
                0.60,
                "folded-cascode wording",
            ),
            ("op amp" in spec or "opamp" in spec, 0.20, "op amp wording"),
            (constraints.get("target_ugbw_hz") is not None, 0.15, "target_ugbw_hz present"),
        ])
        if conf >= 0.50:
            return ("folded_cascode_opamp", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("cascode" in spec, 0.55, "cascode wording"),
        ])
        if conf >= 0.50:
            return ("cascode_amplifier", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("nand" in spec, 0.70, "NAND wording"),
        ])
        if conf >= 0.50:
            return ("nand2_cmos", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("sram" in spec, 0.70, "SRAM wording"),
        ])
        if conf >= 0.50:
            return ("sram6t_cell", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("lc oscillator" in spec or "cross-coupled oscillator" in spec or "cross coupled oscillator" in spec, 0.70, "oscillator wording"),
        ])
        if conf >= 0.50:
            return ("lc_oscillator_cross_coupled", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("gm stage" in spec or "transconductance" in spec or "ota" in spec, 0.55, "gm/ota wording"),
            (constraints.get("target_gm_s") is not None, 0.20, "target_gm_s present"),
        ])
        if conf >= 0.50:
            return ("gm_stage", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("op amp" in spec or "opamp" in spec or "high gain amplifier" in spec, 0.45, "op amp wording"),
            (constraints.get("target_ugbw_hz") is not None, 0.20, "target_ugbw_hz present"),
            (low_power_bias, 0.10, "tight power budget"),
        ])
        if conf >= 0.50:
            return ("two_stage_miller", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("comparator" in spec or "sense amp" in spec or "latched compare" in spec, 0.60, "comparator wording"),
            (constraints.get("input_overdrive_v") is not None, 0.15, "input_overdrive_v present"),
        ])
        if conf >= 0.50:
            return ("comparator", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            (
                "single-stage amplifier" in spec
                or "common source" in spec
                or "common-source" in spec,
                0.45,
                "common-source wording",
            ),
            (constraints.get("target_gain_db") is not None, 0.20, "target_gain_db present"),
            (constraints.get("target_bw_hz") is not None, 0.20, "target_bw_hz present"),
        ])
        if conf >= 0.45:
            return ("common_source_res_load", conf, f"Matched by: {', '.join(reasons)}")

        return None

    def _llm_topology(self, spec: str, constraints: dict, memory: SharedMemory = None):
        if self.llm is None:
            return None

        prompt = f"""
            You are selecting an analog circuit topology.
            Choose the single best topology key.

            Available topology keys:
            {list(TOPOLOGY_LIBRARY.keys())}

            Specification:
            {spec}

            Constraints:
            {constraints}

            Return JSON only:
            {{
            "topology": "<key>",
            "confidence": <0 to 1>,
            "reasoning": "<brief explanation>"
            }}
            """
        result = self.llm.generate(prompt)
        if memory is not None:
            memory.append_history(
                "llm_call",
                {
                    "agent": "TopologyAgent",
                    "task": "topology_selection",
                    "ok": isinstance(result, dict),
                },
            )

        if not isinstance(result, dict):
            return None

        topology = result.get("topology")
        if topology not in TOPOLOGY_LIBRARY:
            return None

        try:
            confidence = float(result.get("confidence", 0.5))
        except Exception:
            confidence = 0.5

        reasoning = result.get("reasoning", "LLM-selected topology.")
        return topology, confidence, reasoning

    def _llm_stage_plan(self, spec_text: str, constraints: dict, max_stage_count: int, memory: SharedMemory = None):
        allowed = [key for key in TOPOLOGY_LIBRARY.keys() if key != "composite_pipeline"]
        prompt = f"""
            You are planning a multi-stage analog circuit pipeline.
            Use only topology keys from this list:
            {allowed}

            Specification:
            {spec_text}

            Constraints:
            {constraints}

            Return JSON only:
            {{
              "mode": "single|composite",
              "confidence": <0 to 1>,
              "reasoning": "<brief explanation>",
              "stages": [
                {{"name": "stage1", "topology": "<key>", "role": "<purpose>"}}
              ]
            }}

            Rules:
            - use at most {max_stage_count} stages
            - if uncertain, prefer 2 stages
            - stage topologies must be valid keys from the allowed list
            """
        result = self.llm.generate(prompt)
        if memory is not None:
            memory.append_history(
                "llm_call",
                {
                    "agent": "TopologyAgent",
                    "task": "stage_plan",
                    "ok": isinstance(result, dict),
                },
            )

        if not isinstance(result, dict):
            return None

        raw_stages = result.get("stages")
        if not isinstance(raw_stages, list):
            return None

        normalized = []
        for idx, item in enumerate(raw_stages[:max_stage_count]):
            if not isinstance(item, dict):
                continue
            topology = item.get("topology")
            if topology not in TOPOLOGY_LIBRARY or topology == "composite_pipeline":
                continue
            normalized.append(
                {
                    "name": item.get("name") or f"stage{idx + 1}",
                    "topology": topology,
                    "role": item.get("role") or f"stage_{idx + 1}",
                }
            )

        if not normalized:
            return None

        try:
            confidence = float(result.get("confidence", 0.7))
        except Exception:
            confidence = 0.7
        confidence = max(0.0, min(1.0, confidence))
        mode = result.get("mode")
        if mode not in {"single", "composite"}:
            mode = "composite" if len(normalized) > 1 else "single"

        return {
            "mode": mode,
            "source": "llm_stage_plan",
            "confidence": confidence,
            "reasoning": result.get("reasoning", "LLM-created stage plan."),
            "stages": normalized,
        }

    def _score_match(self, checks):
        score = 0.0
        reasons = []
        for passed, pts, reason in checks:
            if passed:
                score += pts
                reasons.append(reason)
        return min(score, 0.98), reasons

    def _merged_defaults(self, constraints: dict):
        merged = {}
        merged.update(ANALOG_DEFAULTS.get("process", {}))
        merged.update(ANALOG_DEFAULTS.get("topology_selection", {}))
        merged.update(constraints or {})
        return merged
    
    def _deterministic_fallback(self, constraints: dict, spec: str):
        if constraints.get("target_fc_hz") is not None:
            if constraints.get("response_family") is not None:
                return ("rlc_lowpass_2nd_order", 0.55, "Deterministic fallback from target_fc_hz with response family.")
            return ("rc_lowpass", 0.55, "Deterministic fallback from target_fc_hz.")
        if constraints.get("target_center_hz") is not None and constraints.get("target_bw_hz") is not None:
            return ("rlc_bandpass_2nd_order", 0.55, "Deterministic fallback from center frequency and bandwidth targets.")
        if constraints.get("target_iout_a") is not None:
            return ("current_mirror", 0.55, "Deterministic fallback from target_iout_a.")
        if constraints.get("target_ugbw_hz") is not None:
            return ("two_stage_miller", 0.55, "Deterministic fallback from target_ugbw_hz.")
        if constraints.get("target_gain_db") is not None and constraints.get("target_bw_hz") is not None:
            return ("common_source_res_load", 0.55, "Deterministic fallback from gain and bandwidth targets.")
        return ("common_source_res_load", 0.35, "Last-resort fallback topology.")
