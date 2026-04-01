# I13/agents/topology_agent.py

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory
from core.topology_library import TOPOLOGY_LIBRARY
from core.analog_defaults import ANALOG_DEFAULTS


class TopologyAgent(BaseAgent):
    def run_agent(self, memory: SharedMemory):
        spec = (memory.read("specification") or "").lower()
        constraints = self._merged_defaults(memory.read("constraints") or {})
        case_meta = memory.read("case_metadata") or {}

        if not spec:
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
                llm_result = self._llm_topology(spec, constraints)
                if llm_result is not None:
                    topology, confidence, reasoning = llm_result

        # deterministic fallback so the flow never dies on a missing topology
        if topology not in TOPOLOGY_LIBRARY:
            fallback = self._deterministic_fallback(constraints, spec)
            topology, confidence, reasoning = fallback

        if topology not in TOPOLOGY_LIBRARY:
            memory.write("status", DesignStatus.TOPOLOGY_FAILED)
            memory.write("topology_error", f"Invalid topology returned: {topology}")
            memory.write("topology_raw_response", {"topology": topology})
            return None

        memory.write("selected_topology", topology)
        memory.write("topology_metadata", TOPOLOGY_LIBRARY[topology])
        memory.write("topology_confidence", confidence)
        memory.write("topology_reasoning", reasoning)
        memory.write("status", DesignStatus.TOPOLOGY_SELECTED)
        memory.append_history("topology_selected", topology)

        return {
            "topology": topology,
            "confidence": confidence,
            "reasoning": reasoning,
        }

    def _rule_based_topology(self, spec: str, constraints: dict):
        conf, reasons = self._score_match([
            ("low-pass" in spec or "low pass" in spec or "filter" in spec, 0.45, "filter wording"),
            ("cutoff" in spec, 0.20, "cutoff wording"),
            (constraints.get("target_fc_hz") is not None, 0.20, "target_fc_hz present"),
        ])
        if conf >= 0.50:
            return ("rc_lowpass", conf, f"Matched by: {', '.join(reasons)}")

        conf, reasons = self._score_match([
            ("current mirror" in spec or "bias current" in spec or "copy current" in spec, 0.45, "current mirror wording"),
            (constraints.get("target_iout_a") is not None, 0.20, "target_iout_a present"),
        ])
        if conf >= 0.50:
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
        ])
        if conf >= 0.50:
            return ("two_stage_miller", conf, f"Matched by: {', '.join(reasons)}")

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

    def _llm_topology(self, spec: str, constraints: dict):
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
            return ("rc_lowpass", 0.55, "Deterministic fallback from target_fc_hz.")
        if constraints.get("target_iout_a") is not None:
            return ("current_mirror", 0.55, "Deterministic fallback from target_iout_a.")
        if constraints.get("target_ugbw_hz") is not None:
            return ("two_stage_miller", 0.55, "Deterministic fallback from target_ugbw_hz.")
        if constraints.get("target_gain_db") is not None and constraints.get("target_bw_hz") is not None:
            return ("common_source_res_load", 0.55, "Deterministic fallback from gain and bandwidth targets.")
        return ("common_source_res_load", 0.35, "Last-resort fallback topology.")
