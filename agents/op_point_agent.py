# I13/agents/op_point_agent.py

import os
import re
import shutil
import subprocess
import tempfile

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory


class OpPointAgent(BaseAgent):
    SUPPORTED_TOPOLOGIES = {
        "rc_lowpass",
        "rlc_lowpass_2nd_order",
        "rlc_highpass_2nd_order",
        "rlc_bandpass_2nd_order",
        "common_source_res_load",
        "current_mirror",
        "wilson_current_mirror",
        "cascode_current_mirror",
        "wide_swing_current_mirror",
        "widlar_current_mirror",
        "diff_pair",
        "diff_pair_resistor_load",
        "diff_pair_current_mirror_load",
        "diff_pair_active_load",
        "bjt_diff_pair",
        "gm_stage",
        "two_stage_miller",
        "telescopic_cascode_opamp_core",
        "ldo_error_amp_core",
        "folded_cascode_opamp",
        "folded_cascode_opamp_core",
        "common_drain",
        "adc_input_buffer",
        "adc_reference_buffer",
        "dac_output_buffer",
        "common_gate",
        "source_degenerated_cs",
        "common_source_active_load",
        "diode_connected_stage",
        "cascode_amplifier",
        "transimpedance_frontend",
        "current_sense_amp_helper",
        "compensation_network_helper",
        "adc_anti_alias_rc",
        "dac_reference_conditioning",
        "active_filter_stage",
        "nand2_cmos",
        "sram6t_cell",
        "lc_oscillator_cross_coupled",
        "bandgap_reference_core",
        "comparator",
        "static_comparator",
        "latched_comparator",
    }

    def __init__(self, llm=None, reference_catalog=None, ngspice_path=None, max_op_passes=2, max_retries=1, wait=0):
        super().__init__(llm=llm, reference_catalog=reference_catalog, max_retries=max_retries, wait=wait)
        self.max_op_passes = max_op_passes
        configured = ngspice_path or os.getenv("NGSPICE_PATH")
        if configured and os.path.exists(configured):
            self.ngspice_path = configured
        else:
            self.ngspice_path = self._find_ngspice()

    def run_agent(self, memory: SharedMemory):
        topology = memory.read("selected_topology")
        netlist = memory.read("netlist")
        constraints = memory.read("constraints") or {}
        sizing = memory.read("sizing") or {}
        pass_count = int(memory.read("op_sizing_pass", 0))

        if topology not in self.SUPPORTED_TOPOLOGIES:
            memory.write(
                "op_point_results",
                {"supported": False, "changed": False, "notes": [f"No dedicated OP sizing for topology '{topology}'."]},
            )
            memory.write("status", DesignStatus.OP_SIZING_COMPLETE)
            return None

        if not netlist:
            memory.write("status", DesignStatus.OP_SIZING_FAILED)
            memory.write("op_point_error", "Missing netlist for OP sizing pass.")
            return None

        if not self.ngspice_path:
            payload = {
                "supported": True,
                "changed": False,
                "skipped": True,
                "reason": "ngspice not found for OP sizing pass; continuing with deterministic first-pass sizing.",
                "notes": [
                    "OP sizing skipped because ngspice is unavailable.",
                    "Continuing to simulation stage in degraded mode.",
                ],
            }
            memory.write("op_point_results", payload)
            memory.write("status", DesignStatus.OP_SIZING_COMPLETE)
            return payload

        if pass_count >= self.max_op_passes:
            memory.write(
                "op_point_results",
                {"supported": True, "changed": False, "notes": ["Reached max OP sizing passes; continuing to full simulation."]},
            )
            memory.write("status", DesignStatus.OP_SIZING_COMPLETE)
            return None

        op_netlist = self._build_op_only_netlist(netlist)
        if not op_netlist:
            memory.write("status", DesignStatus.OP_SIZING_FAILED)
            memory.write("op_point_error", "Could not construct OP-only netlist.")
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            netlist_path = os.path.join(tmpdir, "op_pass.sp")
            with open(netlist_path, "w") as f:
                f.write(op_netlist)

            result = subprocess.run(
                [self.ngspice_path, "-b", "-o", "op_pass.log", netlist_path],
                cwd=tmpdir,
                capture_output=True,
                text=True,
            )
            log_path = os.path.join(tmpdir, "op_pass.log")
            if result.returncode != 0 or not os.path.exists(log_path):
                memory.write("status", DesignStatus.OP_SIZING_FAILED)
                memory.write(
                    "op_point_error",
                    f"OP sizing pass failed with return code {result.returncode}.",
                )
                return None

            try:
                with open(log_path, "r") as handle:
                    op_log_text = handle.read()
            except Exception:
                op_log_text = ""

            device_metrics = self._extract_device_metrics_from_log(log_path)
            changed, notes = self._resize_from_op(topology, sizing, constraints, device_metrics, op_log_text)
            op_characterization = self._characterize_operating_point(
                topology=topology,
                sizing=sizing,
                constraints=constraints,
                metrics=device_metrics,
                op_log_text=op_log_text,
            )
            payload = {
                "supported": True,
                "changed": changed,
                "device_metrics": device_metrics,
                "characterization": op_characterization,
                "notes": notes,
                "pass_index": pass_count + 1,
            }
            memory.write("op_point_results", payload)
            memory.write("sizing", sizing)

            if changed:
                memory.write("op_sizing_pass", pass_count + 1)
                memory.write("status", DesignStatus.OP_SIZING_REFINED)
            else:
                memory.write("status", DesignStatus.OP_SIZING_COMPLETE)
            return payload

    def _build_op_only_netlist(self, netlist: str):
        control_match = re.search(r"(?is)\.control(.*?)\.endc", netlist)
        if not control_match:
            return None

        control_body = control_match.group(1)
        kept_lines = []
        for raw in control_body.splitlines():
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if lower.startswith("set "):
                kept_lines.append(line)
            elif lower == "op":
                kept_lines.append(line)
            elif lower.startswith("print ") or lower.startswith("let "):
                kept_lines.append(line)

        if not any(line.lower() == "op" for line in kept_lines):
            kept_lines.insert(0, "op")
        kept_lines.append("quit")

        circuit_body = re.sub(r"(?is)\.control.*?\.endc", "", netlist)
        circuit_body = re.sub(r"(?is)\.end\s*$", "", circuit_body).rstrip()
        return circuit_body + "\n\n.control\n" + "\n".join(kept_lines) + "\n.endc\n.end\n"

    def _extract_device_metrics_from_log(self, log_path):
        try:
            with open(log_path, "r") as f:
                text = f.read()
        except Exception:
            return {}

        metrics = {}
        pattern = re.compile(
            r"@(?P<device>[a-z0-9_]+)\[(?P<metric>[a-z0-9_]+)\]\s*=\s*(?P<value>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            device = match.group("device").lower()
            metric = match.group("metric").lower()
            try:
                value = float(match.group("value"))
            except ValueError:
                continue
            metrics.setdefault(device, {})[metric] = value
        return metrics

    def _metric(self, metrics, device, metric):
        return ((metrics.get(device.lower()) or {}).get(metric.lower()))

    def _metric_any(self, metrics, devices, metric):
        for device in devices:
            value = self._metric(metrics, device, metric)
            if value is not None:
                return value
        return None

    def _extract_named_value_from_text(self, text, token):
        if not text:
            return None
        pattern = re.compile(
            rf"{re.escape((token or '').lower())}\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
            re.IGNORECASE,
        )
        match = pattern.search(text.lower())
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _clamp_scale(self, factor, lower=0.7, upper=1.35):
        try:
            value = float(factor)
        except Exception:
            value = 1.0
        return max(float(lower), min(float(upper), value))

    def _first_existing_key(self, mapping, keys):
        for key in keys:
            if key in mapping:
                return key
        return None

    def _resize_from_op(self, topology, sizing, constraints, metrics, op_log_text=""):
        if topology in {
            "common_source_res_load",
            "common_drain",
            "common_gate",
            "source_degenerated_cs",
            "common_source_active_load",
            "diode_connected_stage",
            "cascode_amplifier",
        }:
            return self._resize_single_stage_from_op(sizing, constraints, metrics)
        if topology in {"current_mirror", "wilson_current_mirror", "cascode_current_mirror", "widlar_current_mirror"}:
            return self._resize_mirror_from_op(sizing, constraints, metrics)
        if topology in {"diff_pair", "bjt_diff_pair"}:
            return self._resize_diff_pair_from_op(sizing, constraints, metrics)
        if topology == "gm_stage":
            return self._resize_gm_stage_from_op(sizing, constraints, metrics)
        if topology in {"two_stage_miller", "folded_cascode_opamp"}:
            return self._resize_opamp_from_op(sizing, constraints, metrics, op_log_text)
        if topology == "bandgap_reference_core":
            return self._resize_bandgap_from_op(sizing, constraints, op_log_text)
        return self._resize_generic_from_op(topology, sizing, constraints, metrics)

    def _resize_single_stage_from_op(self, sizing, constraints, metrics):
        gm = self._metric_any(metrics, ["m1", "mnin", "mn1"], "gm")
        gds = self._metric_any(metrics, ["m1", "mnin", "mn1"], "gds")
        vgs = self._metric_any(metrics, ["m1", "mnin", "mn1"], "vgs")
        vds = self._metric_any(metrics, ["m1", "mnin", "mn1"], "vds")
        current = self._metric_any(metrics, ["m1", "mnin", "mn1"], "id")
        gm_id_target = float(sizing.get("gm_id_target_s_per_a", constraints.get("gm_id_target_s_per_a", 12.0)))
        vth = float(constraints.get("vth_n_v", 0.5))
        notes = []
        changed = False

        width_key = self._first_existing_key(sizing, ["W_m", "W_n", "W_in"])
        length_key = self._first_existing_key(sizing, ["L_m", "L_n", "L_in"])
        bias_key = self._first_existing_key(sizing, ["I_bias", "I_tail"])

        if gm is not None and current not in (None, 0) and width_key is not None:
            gm_id_meas = abs(float(gm) / max(float(current), 1e-18))
            if gm_id_meas < 0.9 * gm_id_target:
                old = float(sizing[width_key])
                sizing[width_key] = old * self._clamp_scale(gm_id_target / max(gm_id_meas, 1e-30), lower=1.05, upper=1.25)
                changed = True
                notes.append(
                    f"Measured gm/Id={gm_id_meas:.3g} S/A below target {gm_id_target:.3g}. "
                    f"Increased {width_key}."
                )
            elif gm_id_meas > 1.25 * gm_id_target:
                old = float(sizing[width_key])
                sizing[width_key] = max(1e-9, old * self._clamp_scale(gm_id_target / gm_id_meas, lower=0.80, upper=0.98))
                changed = True
                notes.append(
                    f"Measured gm/Id={gm_id_meas:.3g} S/A above target {gm_id_target:.3g}. "
                    f"Reduced {width_key}."
                )

        if vgs is not None and vds is not None and bias_key is not None:
            vov = max(float(vgs) - vth, 1e-3)
            if float(vds) < 1.05 * vov:
                old = float(sizing[bias_key])
                sizing[bias_key] = max(1e-12, old * 0.88)
                changed = True
                notes.append(f"Measured Vds is too close to Vov. Reduced {bias_key} for more saturation margin.")

        if gds is not None and length_key is not None and constraints.get("target_gain_db") is not None:
            ro = 1.0 / max(abs(float(gds)), 1e-18)
            gm_abs = abs(float(gm or 0.0))
            intrinsic_gain = gm_abs * ro
            target_gain_linear = 10 ** (float(constraints.get("target_gain_db", 10.0)) / 20.0)
            if intrinsic_gain < 0.7 * target_gain_linear:
                old = float(sizing[length_key])
                sizing[length_key] = old * 1.10
                changed = True
                notes.append("Measured intrinsic gain from OP is low. Increased channel length.")

        return changed, notes or ["No OP-driven resize applied."]

    def _resize_mirror_from_op(self, sizing, constraints, metrics):
        current = self._metric_any(metrics, ["mout", "m2", "moutc"], "id")
        target_i = constraints.get("target_iout_a")
        if current is None or target_i is None or "W_out" not in sizing:
            return False, ["Missing measured mirror current or W_out for OP resizing."]
        current = abs(float(current))
        target_i = abs(float(target_i))
        if current <= 0:
            return False, ["Measured mirror current was non-positive during OP sizing."]
        ratio = target_i / current
        if 0.92 <= ratio <= 1.08:
            return False, ["Mirror OP current already close to target."]
        old = float(sizing["W_out"])
        scale = self._clamp_scale(ratio, lower=0.75, upper=1.35)
        sizing["W_out"] = old * scale
        if "W_cas" in sizing:
            sizing["W_cas"] = float(sizing["W_cas"]) * scale
        if "W_aux" in sizing:
            # In Wilson mirrors the feedback device can over-constrain output current;
            # counter-scale W_aux to recover target copy current when far off.
            aux_scale = self._clamp_scale(1.0 / max(ratio, 1e-30), lower=0.75, upper=1.35)
            sizing["W_aux"] = float(sizing["W_aux"]) * aux_scale
        return True, [f"Adjusted mirror sizing from measured OP current {current:.3g} A toward {target_i:.3g} A."]

    def _resize_diff_pair_from_op(self, sizing, constraints, metrics):
        gm = self._metric_any(metrics, ["m1", "q1"], "gm")
        current = self._metric_any(metrics, ["m1", "q1"], "id")
        vgs = self._metric(metrics, "m1", "vgs")
        vds = self._metric(metrics, "m1", "vds")
        gm_id_target = float(sizing.get("gm_id_target_s_per_a", constraints.get("gm_id_target_s_per_a", 12.0)))
        vth = float(constraints.get("vth_n_v", 0.5))
        notes = []
        changed = False

        if gm is not None and current not in (None, 0) and "W_in" in sizing:
            gm_id_meas = abs(float(gm) / max(float(current), 1e-18))
            if gm_id_meas < 0.9 * gm_id_target:
                old = float(sizing["W_in"])
                sizing["W_in"] = old * 1.12
                changed = True
                notes.append("Input-pair gm/Id below target. Increased W_in.")

        if vgs is not None and vds is not None and "I_tail" in sizing:
            vov = max(float(vgs) - vth, 1e-3)
            if float(vds) < 1.05 * vov:
                old = float(sizing["I_tail"])
                sizing["I_tail"] = max(1e-12, old * 0.90)
                changed = True
                notes.append("Diff-pair input device is too close to triode. Reduced I_tail.")

        return changed, notes or ["No OP-driven diff-pair resize applied."]

    def _resize_gm_stage_from_op(self, sizing, constraints, metrics):
        gm = self._metric(metrics, "m1", "gm")
        target_gm = constraints.get("target_gm_s", sizing.get("gm_target_s"))
        if gm is None or target_gm is None:
            return False, ["No gm measurement available for gm-stage OP refinement."]
        gm = abs(float(gm))
        target_gm = abs(float(target_gm))
        if gm <= 0:
            return False, ["Measured gm was non-positive during OP refinement."]
        ratio = target_gm / gm
        if 0.90 <= ratio <= 1.10:
            return False, ["Measured gm already close to gm target."]
        notes = []
        changed = False
        if "W_m" in sizing:
            old = float(sizing["W_m"])
            sizing["W_m"] = max(1e-9, old * self._clamp_scale(ratio, lower=0.8, upper=1.3))
            changed = True
            notes.append("Adjusted W_m from measured gm toward target gm.")
        if "I_bias_a" in sizing:
            old = float(sizing["I_bias_a"])
            sizing["I_bias_a"] = max(1e-12, old * self._clamp_scale(ratio, lower=0.85, upper=1.25))
            changed = True
            notes.append("Adjusted I_bias_a from measured gm toward target gm.")
        return changed, notes or ["No gm-stage OP refinement applied."]

    def _resize_opamp_from_op(self, sizing, constraints, metrics, op_log_text):
        notes = []
        changed = False
        supply_v = constraints.get("supply_v")
        power_limit_mw = constraints.get("power_limit_mw")
        ivdd = self._extract_named_value_from_text(op_log_text, "i(vdd)")

        if ivdd is not None and supply_v is not None and power_limit_mw is not None:
            power_mw = 1000.0 * abs(float(ivdd)) * float(supply_v)
            if power_mw > 1.05 * float(power_limit_mw):
                scale = self._clamp_scale(float(power_limit_mw) / max(power_mw, 1e-30), lower=0.70, upper=0.97)
                for key in ("I_stage1_a", "I_stage2_a", "I_tail"):
                    if key in sizing:
                        sizing[key] = max(1e-12, float(sizing[key]) * scale)
                        changed = True
                if changed:
                    notes.append(
                        f"OP-estimated power ({power_mw:.3g} mW) exceeds limit ({float(power_limit_mw):.3g} mW). "
                        "Reduced bias currents."
                    )

        gm_meas = self._metric_any(metrics, ["m1", "mnin"], "gm")
        if gm_meas is not None and "gm1_target_s" in sizing:
            gm_target = float(sizing["gm1_target_s"])
            gm_ratio = gm_target / max(abs(float(gm_meas)), 1e-30)
            if gm_ratio > 1.2:
                sizing["gm1_target_s"] = gm_target * self._clamp_scale(gm_ratio, lower=1.05, upper=1.25)
                changed = True
                notes.append("Measured first-stage gm is below target. Increased gm1_target_s.")

        return changed, notes or ["No OP-driven op-amp resize applied."]

    def _resize_bandgap_from_op(self, sizing, constraints, op_log_text):
        target_vref = constraints.get("target_vref_v")
        measured_vref = self._extract_named_value_from_text(op_log_text, "v(ref)")
        if target_vref is None or measured_vref is None or "R2_ohm" not in sizing:
            return False, ["No bandgap OP resize applied (missing Vref target, OP Vref, or R2_ohm)."]
        measured_vref = float(measured_vref)
        target_vref = float(target_vref)
        if measured_vref <= 0:
            return False, ["Measured Vref was non-positive during OP refinement."]
        ratio = target_vref / measured_vref
        if 0.97 <= ratio <= 1.03:
            return False, ["Bandgap OP Vref already close to target."]
        old = float(sizing["R2_ohm"])
        sizing["R2_ohm"] = old * self._clamp_scale(ratio, lower=0.80, upper=1.25)
        return True, [f"Adjusted R2_ohm from OP Vref {measured_vref:.4g} V toward {target_vref:.4g} V."]

    def _resize_generic_from_op(self, topology, sizing, constraints, metrics):
        gm = self._metric_any(metrics, ["m1", "mn1"], "gm")
        current = self._metric_any(metrics, ["m1", "mn1"], "id")
        width_key = self._first_existing_key(sizing, ["W_m", "W_n", "W_in"])
        gm_id_target = float(sizing.get("gm_id_target_s_per_a", constraints.get("gm_id_target_s_per_a", 12.0)))

        if gm is None or current in (None, 0) or width_key is None:
            return False, [f"No dedicated OP resizing rule for topology '{topology}', and generic gm/Id data was unavailable."]

        gm_id = abs(float(gm) / max(float(current), 1e-30))
        if 0.9 * gm_id_target <= gm_id <= 1.25 * gm_id_target:
            return False, [f"No dedicated OP resizing rule for topology '{topology}'. Generic gm/Id check is already in range."]

        old = float(sizing[width_key])
        sizing[width_key] = max(1e-9, old * self._clamp_scale(gm_id_target / gm_id, lower=0.8, upper=1.25))
        return True, [f"Applied generic OP gm/Id resize for topology '{topology}' by adjusting {width_key}."]

    def _characterize_operating_point(self, topology, sizing, constraints, metrics, op_log_text):
        vth = float(constraints.get("vth_n_v", 0.5))
        device_summary = {}
        near_triode = []

        for device, values in (metrics or {}).items():
            gm = values.get("gm")
            gds = values.get("gds")
            current = values.get("id")
            vgs = values.get("vgs")
            vds = values.get("vds")
            gm_id = None
            ro = None
            intrinsic_gain = None
            if gm is not None and current not in (None, 0):
                gm_id = abs(float(gm) / max(float(current), 1e-30))
            if gds not in (None, 0):
                ro = 1.0 / max(abs(float(gds)), 1e-30)
            if gm is not None and ro is not None:
                intrinsic_gain = abs(float(gm)) * ro
            if vgs is not None and vds is not None:
                vov = max(float(vgs) - vth, 0.0)
                if float(vds) < 1.05 * vov:
                    near_triode.append(device)
            device_summary[device] = {
                "gm_s": gm,
                "gds_s": gds,
                "id_a": current,
                "vgs_v": vgs,
                "vds_v": vds,
                "gm_id_s_per_a": gm_id,
                "ro_ohm": ro,
                "intrinsic_gain_vv": intrinsic_gain,
            }

        ivdd = self._extract_named_value_from_text(op_log_text, "i(vdd)")
        supply_v = constraints.get("supply_v")
        power_mw = None
        if ivdd is not None and supply_v is not None:
            power_mw = 1000.0 * abs(float(ivdd)) * float(supply_v)

        return {
            "topology": topology,
            "device_count": len(device_summary),
            "near_triode_devices": near_triode,
            "supply_current_a": abs(float(ivdd)) if ivdd is not None else None,
            "estimated_power_mw": power_mw,
            "devices": device_summary,
        }

    def _find_ngspice(self):
        candidates = [
            shutil.which("ngspice"),
            "/opt/homebrew/bin/ngspice",
            "/usr/local/bin/ngspice",
        ]
        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None
