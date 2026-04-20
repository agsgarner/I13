# I13/agents/simulation_agent.py

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from html import escape
from datetime import datetime
from core.analog_defaults import ANALOG_DEFAULTS
from core.demo_catalog import slugify_label

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory


class SimulationAgent(BaseAgent):
    AC_EXPECTED_TOPOLOGIES = {
        "composite_pipeline",
        "rc_lowpass",
        "rlc_lowpass_2nd_order",
        "rlc_highpass_2nd_order",
        "rlc_bandpass_2nd_order",
        "common_source_res_load",
        "diff_pair",
        "two_stage_miller",
        "folded_cascode_opamp",
        "gm_stage",
        "common_drain",
        "common_gate",
        "source_degenerated_cs",
        "common_source_active_load",
        "diode_connected_stage",
        "cascode_amplifier",
    }

    def __init__(self, llm=None, ngspice_path=None, max_retries=1, wait=0):
        super().__init__(llm=llm, max_retries=max_retries, wait=wait)
        self.ngspice_path = ngspice_path or os.getenv("NGSPICE_PATH") or self._find_ngspice()

    def run_agent(self, memory: SharedMemory):
        netlist = memory.read("netlist")
        topology = memory.read("selected_topology")
        sizing = memory.read("sizing") or {}
        constraints = self._merged_constraints(memory)

        if not netlist:
            memory.write("status", DesignStatus.SIMULATION_FAILED)
            memory.write("simulation_error", "Missing netlist")
            return None

        if not self.ngspice_path:
            memory.write("status", DesignStatus.SIMULATION_FAILED)
            memory.write("simulation_error", "ngspice not found")
            return None

        run_id = self._build_run_id(memory, topology)
        base_dir = os.path.join("artifacts", "simulations", run_id)
        os.makedirs(base_dir, exist_ok=True)
        case_meta = memory.read("case_metadata") or {}
        simulation_plan = case_meta.get("simulation_plan") or {}
        planned_analyses = set(simulation_plan.get("analyses") or [])
        manifest = {
            "case_key": case_meta.get("case_key"),
            "display_name": case_meta.get("display_name"),
            "artifact_label": case_meta.get("artifact_label"),
            "topology": topology,
            "attempt": int(memory.read("iteration", 0)) + 1,
            "analyses": simulation_plan.get("analyses", []),
            "intent": simulation_plan.get("intent"),
            "primary_metrics": simulation_plan.get("primary_metrics", []),
        }
        self._safe_write_text(
            os.path.join(base_dir, "run_manifest.json"),
            self._to_json(manifest),
        )

        saved_netlist_path = os.path.join(base_dir, "generated.sp")
        with open(saved_netlist_path, "w") as f:
            f.write(netlist)

        result = subprocess.run(
            [self.ngspice_path, "-b", "-o", "ngspice.log", "generated.sp"],
            cwd=base_dir,
            capture_output=True,
            text=True
        )

        sim = {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "saved_netlist_path": saved_netlist_path,
            "artifact_dir": base_dir,
            "ngspice_path": self.ngspice_path,
            "analyses": simulation_plan.get("analyses", []),
            "intent": simulation_plan.get("intent"),
            "simulation_provenance": "Executed directly from artifact generated.sp",
            "plot_validations": [],
            "netlist_stage_report": memory.read("netlist_stage_report"),
        }

        self._safe_write_text(os.path.join(base_dir, "stdout.txt"), result.stdout or "")
        self._safe_write_text(os.path.join(base_dir, "stderr.txt"), result.stderr or "")

        log_path = os.path.join(base_dir, "ngspice.log")

        if result.returncode != 0:
            memory.write("simulation_results", sim)
            memory.write("status", DesignStatus.SIMULATION_FAILED)
            return sim

        ac_csv = os.path.join(base_dir, "ac_out.csv")
        dc_csv = os.path.join(base_dir, "dc_out.csv")
        tran_in_csv = os.path.join(base_dir, "tran_in.csv")
        tran_out_csv = os.path.join(base_dir, "tran_out.csv")

        # -------------------------
        # AC artifacts
        # -------------------------
        if os.path.exists(ac_csv):
            sim["ac_csv"] = ac_csv
            sim["ac_preview"] = self._preview_file(ac_csv, max_lines=8)

            ac_data = self._read_ngspice_ac(ac_csv)
            ac_validation = self._validate_xy_data(
                name="ac_dataset",
                data=ac_data,
                min_points=8,
                x_monotonic=True,
                x_positive=True,
            )
            sim["plot_validations"].append(ac_validation)

            if ac_data["x"] and ac_data["y"]:
                sim["ac_points"] = len(ac_data["x"])
                ac_plot = os.path.join(base_dir, "ac_plot.svg")
                input_ac_mag = float(constraints.get("vin_ac", 1.0))
                if topology == "diff_pair":
                    input_ac_mag *= 2.0
                self._plot_ac(ac_data, ac_plot, input_ac_mag=input_ac_mag)
                sim["ac_plot"] = ac_plot
                sim["plot_validations"].append(self._validate_plot_file("ac_plot", ac_plot))
                sim["ac_characterization"] = self._characterize_ac_response(
                    ac_data,
                    input_ac_mag=input_ac_mag,
                )
                gain_db, bw_hz = self._extract_gain_bw_from_ac(ac_data, input_ac_mag=input_ac_mag)
                ugbw_hz = self._extract_unity_gain_bw_from_ac(ac_data, input_ac_mag=input_ac_mag)

                if gain_db is not None:
                    sim["gain_db"] = gain_db
                if bw_hz is not None:
                    sim["bandwidth_hz"] = bw_hz
                if ugbw_hz is not None:
                    sim["ugbw_hz"] = ugbw_hz

                if topology in {"rc_lowpass", "rlc_lowpass_2nd_order"}:
                    sim["fc_hz_from_ac"] = self._estimate_cutoff_from_ac(ac_data)
                elif topology == "rlc_highpass_2nd_order":
                    sim["fc_hz_from_ac"] = self._estimate_highpass_cutoff_from_ac(
                        ac_data,
                        input_ac_mag=input_ac_mag,
                    )
                elif topology == "rlc_bandpass_2nd_order":
                    sim.update(
                        self._estimate_bandpass_metrics_from_ac(
                            ac_data,
                            input_ac_mag=input_ac_mag,
                        )
                    )
            else:
                sim["parser_warning"] = (
                    "AC file was created, but parser could not extract usable AC points."
                )
        elif "ac" in planned_analyses:
            sim["plot_validations"].append(
                {
                    "name": "ac_dataset",
                    "status": "fail",
                    "issues": ["Missing ac_out.csv even though AC analysis was planned."],
                    "warnings": [],
                }
            )
        elif topology in self.AC_EXPECTED_TOPOLOGIES:
            if topology == "rc_lowpass":
                sim["parser_warning"] = (
                    "ac_out.csv was not created by ngspice; using formula-based cutoff."
                )
            else:
                sim["parser_warning"] = (
                    "ac_out.csv was not created by ngspice; AC metrics could not be extracted."
                )

        # -------------------------
        # DC artifacts
        # -------------------------
        if os.path.exists(dc_csv):
            sim["dc_csv"] = dc_csv
            sim["dc_preview"] = self._preview_file(dc_csv, max_lines=8)

            dc_data = self._read_wrdata_xy(dc_csv)
            sim["plot_validations"].append(
                self._validate_xy_data(
                    name="dc_dataset",
                    data=dc_data,
                    min_points=6,
                    x_monotonic=True,
                    x_positive=False,
                )
            )
            if dc_data["x"] and dc_data["y"]:
                sim["dc_points"] = len(dc_data["x"])
                dc_plot = os.path.join(base_dir, "dc_plot.svg")
                self._plot_dc(dc_data, dc_plot, xlabel="Sweep Variable", ylabel="Output")
                sim["dc_plot"] = dc_plot
                sim["plot_validations"].append(self._validate_plot_file("dc_plot", dc_plot))
        elif "dc" in planned_analyses:
            sim["plot_validations"].append(
                {
                    "name": "dc_dataset",
                    "status": "fail",
                    "issues": ["Missing dc_out.csv even though DC analysis was planned."],
                    "warnings": [],
                }
            )

        # -------------------------
        # Transient artifacts
        # -------------------------
        tran_series = {}
        tran_in_data = None
        tran_out_data = None
        tran_qb_data = None
        tran_diff_data = None

        if os.path.exists(tran_in_csv):
            sim["tran_in_csv"] = tran_in_csv
            tran_in_data = self._read_wrdata_xy(tran_in_csv)
            tran_series["V(in)"] = tran_in_data

        if os.path.exists(tran_out_csv):
            sim["tran_out_csv"] = tran_out_csv
            sim["tran_preview"] = self._preview_file(tran_out_csv, max_lines=5)
            tran_out_data = self._read_wrdata_xy(tran_out_csv)
            tran_series["V(out)"] = tran_out_data

        extra_tran_specs = [
            ("tran_in_a.csv", "tran_in_a_csv", "V(in_a)"),
            ("tran_in_b.csv", "tran_in_b_csv", "V(in_b)"),
            ("tran_bl.csv", "tran_bl_csv", "V(BL)"),
            ("tran_blb.csv", "tran_blb_csv", "V(BLB)"),
            ("tran_wl.csv", "tran_wl_csv", "V(WL)"),
            ("tran_outn.csv", "tran_outn_csv", "V(outn)"),
            ("tran_out_limited.csv", "tran_out_limited_csv", "V(out_limited)"),
        ]
        for filename, sim_key, label in extra_tran_specs:
            candidate = os.path.join(base_dir, filename)
            if os.path.exists(candidate):
                sim[sim_key] = candidate
                tran_series[label] = self._read_wrdata_xy(candidate)

        tran_qb_csv = os.path.join(base_dir, "tran_qb.csv")
        if os.path.exists(tran_qb_csv):
            sim["tran_qb_csv"] = tran_qb_csv
            tran_qb_data = self._read_wrdata_xy(tran_qb_csv)
            tran_series["V(QB)"] = tran_qb_data

        tran_diff_csv = os.path.join(base_dir, "tran_diff.csv")
        if os.path.exists(tran_diff_csv):
            sim["tran_diff_csv"] = tran_diff_csv
            tran_diff_data = self._read_wrdata_xy(tran_diff_csv)
            tran_series["V(outp,outn)"] = tran_diff_data

        if tran_out_data and tran_out_data["x"] and tran_out_data["y"]:
            tran_plot = os.path.join(base_dir, "tran_plot.svg")
            self._plot_tran_series(tran_series, tran_plot)
            sim["tran_plot"] = tran_plot
            sim["tran_points"] = len(tran_out_data["x"])
            sim["plot_validations"].append(self._validate_plot_file("tran_plot", tran_plot))

        if tran_out_data:
            sim["plot_validations"].append(
                self._validate_xy_data(
                    name="tran_dataset",
                    data=tran_out_data,
                    min_points=10,
                    x_monotonic=True,
                    x_positive=False,
                )
            )
            if tran_in_data:
                sim["transient_characterization"] = self._characterize_step_response(
                    tran_in_data=tran_in_data,
                    tran_out_data=tran_out_data,
                )
                transient_gain_db = (sim.get("transient_characterization") or {}).get("transient_gain_db")
                if transient_gain_db is not None:
                    sim["transient_gain_db"] = transient_gain_db
        elif "tran" in planned_analyses:
            sim["plot_validations"].append(
                {
                    "name": "tran_dataset",
                    "status": "fail",
                    "issues": ["Missing tran_out.csv even though transient analysis was planned."],
                    "warnings": [],
                }
            )

        if os.path.exists(log_path):
            sim["log_path"] = log_path
            sim["log_preview"] = self._preview_file(log_path, max_lines=20)
            device_metrics = self._extract_device_metrics_from_log(log_path)
            if device_metrics:
                sim["device_metrics"] = device_metrics

            if topology in {
                "current_mirror",
                "wilson_current_mirror",
                "cascode_current_mirror",
                "widlar_current_mirror",
            }:
                sim_i = self._extract_current_from_log(sim.get("log_preview"))
                if sim_i is not None:
                    sim["iout_a"] = abs(sim_i)

            if topology == "bandgap_reference_core":
                vref = self._extract_named_voltage_from_log(sim.get("log_preview"), "v(ref)")
                if vref is not None:
                    sim["vref_v"] = vref

            supply_i = self._extract_named_current_from_log(sim.get("log_preview"), "i(vdd)")
            if supply_i is not None:
                sim["supply_current_a"] = abs(supply_i)

            if topology in (
                "common_source_res_load",
                "source_degenerated_cs",
                "common_source_active_load",
                "diode_connected_stage",
                "cascode_amplifier",
                "common_drain",
                "common_gate",
                "diff_pair",
                "two_stage_miller",
                "folded_cascode_opamp",
                "bandgap_reference_core",
            ):
                sim["op_summary"] = self._extract_op_region_summary(sim.get("log_preview"))

            if topology == "lc_oscillator_cross_coupled":
                aborted = any("aborted" in (line or "").lower() for line in sim.get("log_preview", []))
                if aborted:
                    sim["parser_warning"] = (
                        "Transient oscillation run was numerically unstable; using LC tank formula estimate."
                    )


        # -------------------------
        # RC cutoff logic
        # -------------------------
            if topology == "rc_lowpass":
                fc_formula = self._formula_fc_from_sizing(sizing)
                sim["fc_hz_formula"] = fc_formula

                fc_ac = sim.get("fc_hz_from_ac")

                if fc_formula is not None:
                    if fc_ac is None:
                        sim["fc_hz"] = fc_formula
                        if "parser_warning" not in sim:
                            sim["parser_warning"] = (
                                "No usable AC-derived cutoff found. Using formula-based cutoff."
                            )
                    else:
                        rel_diff = abs(fc_ac - fc_formula) / max(fc_formula, 1e-30)
                        if rel_diff > 0.50:
                            sim["fc_hz"] = fc_formula
                            sim["parser_warning"] = (
                                f"AC-derived cutoff ({fc_ac:.6g} Hz) disagreed strongly with "
                                f"formula-based cutoff ({fc_formula:.6g} Hz). Using formula-based cutoff."
                            )
                        else:
                            sim["fc_hz"] = fc_ac
                else:
                    sim["fc_hz"] = fc_ac

            if topology in {"rlc_lowpass_2nd_order", "rlc_highpass_2nd_order"}:
                sim.pop("gain_db", None)
                sim.pop("bandwidth_hz", None)
                sim["fc_hz"] = sim.get("fc_hz_from_ac") or sizing.get("target_fc_hz")
                sim["q_factor"] = sizing.get("q_target")
                sim["damping_ratio"] = sizing.get("damping_ratio")
                sim["rolloff_db_per_dec"] = sizing.get("rolloff_db_per_dec")
                sim["response_family"] = sizing.get("response_family")

            if topology == "rlc_bandpass_2nd_order":
                sim.pop("gain_db", None)
                sim.setdefault("center_hz", sizing.get("target_center_hz"))
                sim.setdefault("bandwidth_hz", sizing.get("target_bw_hz"))
                sim["q_factor"] = sim.get("q_factor") or ((sim.get("ac_characterization") or {}).get("estimated_q")) or sizing.get("q_target")
                sim["damping_ratio"] = sizing.get("damping_ratio")
                sim["rolloff_db_per_dec"] = sizing.get("rolloff_db_per_dec")
                sim["response_family"] = sizing.get("response_family")
            
            if topology in (
                "common_source_res_load",
                "source_degenerated_cs",
                "common_source_active_load",
                "diode_connected_stage",
                "cascode_amplifier",
                "common_drain",
                "common_gate",
            ):
                vdd = memory.read("constraints").get("supply_v")
                supply_i = sim.get("supply_current_a")
                ibias = sizing.get("I_bias")
                current_for_power = supply_i if supply_i is not None else ibias
                if vdd is not None and current_for_power is not None:
                    sim["power_mw"] = 1000.0 * float(vdd) * float(current_for_power)

            if topology in {"diff_pair", "two_stage_miller"}:
                vdd = memory.read("constraints").get("supply_v")
                supply_i = sim.get("supply_current_a")
                if vdd is not None and supply_i is not None and supply_i > 0:
                    sim["power_mw"] = 1000.0 * float(vdd) * float(supply_i)
                elif topology == "two_stage_miller":
                    fallback_i = float(sizing.get("I_stage1_a", 0.0)) + float(sizing.get("I_stage2_a", 0.0))
                    if fallback_i > 0:
                        sim["power_mw"] = 1000.0 * float(vdd) * fallback_i

            if topology == "folded_cascode_opamp":
                vdd = memory.read("constraints").get("supply_v")
                supply_i = sim.get("supply_current_a")
                fallback_i = float(sizing.get("I_tail", 0.0))
                if vdd is not None and supply_i is not None and supply_i > 0:
                    sim["power_mw"] = 1000.0 * float(vdd) * float(supply_i)
                elif vdd is not None and fallback_i > 0:
                    sim["power_mw"] = 1000.0 * float(vdd) * fallback_i

            if topology == "composite_pipeline":
                vdd = memory.read("constraints").get("supply_v")
                supply_i = sim.get("supply_current_a")
                if vdd is not None and supply_i is not None and supply_i > 0:
                    sim["power_mw"] = 1000.0 * float(vdd) * float(supply_i)
                elif vdd is not None:
                    stage_currents = []
                    for stage in (sizing.get("stages") or []):
                        stage_sizing = stage.get("sizing") or {}
                        for key in (
                            "I_bias",
                            "I_tail",
                            "tail_current_a",
                            "I_stage1_a",
                            "I_stage2_a",
                            "I_core",
                            "I_ref",
                        ):
                            value = stage_sizing.get(key)
                            if value is None:
                                continue
                            try:
                                stage_currents.append(float(value))
                                break
                            except Exception:
                                continue
                    fallback_i = sum(item for item in stage_currents if item > 0)
                    if fallback_i > 0:
                        sim["power_mw"] = 1000.0 * float(vdd) * fallback_i
                if isinstance(sizing.get("stages"), list):
                    sim["composite_stage_count"] = len(sizing.get("stages"))

            if topology == "bandgap_reference_core":
                vdd = memory.read("constraints").get("supply_v")
                supply_i = sim.get("supply_current_a")
                if vdd is not None and supply_i is not None:
                    sim["power_mw"] = 1000.0 * float(vdd) * float(supply_i)

            power_limit_mw = memory.read("constraints").get("power_limit_mw")
            if power_limit_mw is not None and sim.get("power_mw") is not None:
                sim["power_limit_mw"] = float(power_limit_mw)
                sim["power_margin_mw"] = float(power_limit_mw) - float(sim["power_mw"])
                sim["power_limit_ok"] = sim["power_mw"] <= float(power_limit_mw)

            if topology == "lc_oscillator_cross_coupled":
                osc_data = tran_diff_data or tran_out_data
                f_osc = self._estimate_oscillation_frequency(osc_data)
                if f_osc is not None:
                    sim["oscillation_hz"] = f_osc
                else:
                    f_formula = self._estimate_lc_formula_frequency(sizing)
                    if f_formula is not None:
                        sim["oscillation_hz"] = f_formula

            if topology == "sram6t_cell":
                vdd = float(memory.read("constraints").get("supply_v", 1.2))
                q_final = self._last_value(tran_out_data)
                qb_final = self._last_value(tran_qb_data)
                if q_final is not None:
                    sim["q_final_v"] = q_final
                if qb_final is not None:
                    sim["qb_final_v"] = qb_final
                if q_final is not None and qb_final is not None:
                    sim["write_ok"] = (q_final > 0.7 * vdd) and (qb_final < 0.3 * vdd)

            if topology == "bandgap_reference_core" and sim.get("vref_v") is None:
                vref = self._last_value(tran_out_data)
                if vref is not None:
                    sim["vref_v"] = vref

            if topology == "comparator":
                comparator_metrics = self._extract_comparator_metrics(
                    tran_in_data,
                    tran_out_data,
                    float(memory.read("constraints").get("supply_v", 1.8)),
                )
                sim.update(comparator_metrics)

            if topology == "nand2_cmos" and tran_out_data and tran_out_data.get("y"):
                vout = [float(v) for v in tran_out_data["y"]]
                sim["logic_low_v"] = min(vout)
                sim["logic_high_v"] = max(vout)
                sim["logic_swing_v"] = sim["logic_high_v"] - sim["logic_low_v"]

            sim["plot_validation_summary"] = self._summarize_plot_validations(sim.get("plot_validations", []))

            verification_summary = self._build_verification_summary(
                topology=topology,
                sizing=sizing,
                constraints=memory.read("constraints") or {},
                sim=sim,
            )
            sim["verification_summary"] = verification_summary
            memory.write("verification_summary", verification_summary)
                    
            memory.write("simulation_results", sim)
            memory.write("status", DesignStatus.SIMULATION_COMPLETE)
            return sim

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

    def _build_run_id(self, memory: SharedMemory, topology: str):
        case_meta = memory.read("case_metadata") or {}
        attempt = int(memory.read("iteration", 0)) + 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        topology_slug = slugify_label(topology or "unknown")
        case_slug = slugify_label(case_meta.get("artifact_label") or case_meta.get("case_key") or "case")
        analyses = (case_meta.get("simulation_plan") or {}).get("analyses") or []
        analysis_slug = "-".join(analyses) if analyses else "sim"
        return os.path.join(
            case_slug,
            f"{case_slug}__{topology_slug}__{analysis_slug}__attempt-{attempt:02d}__{timestamp}",
        )

    def _get_pyplot(self):
        try:
            mpl_dir = os.path.join(tempfile.gettempdir(), "i13-mplconfig")
            os.makedirs(mpl_dir, exist_ok=True)
            os.environ.setdefault("MPLCONFIGDIR", mpl_dir)

            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            return plt
        except Exception:
            return None

    def _safe_write_text(self, path, text):
        with open(path, "w") as f:
            f.write(text)

    def _to_json(self, value):
        return json.dumps(value, indent=2, sort_keys=True)

    def _preview_file(self, path, max_lines=5):
        preview = []
        try:
            with open(path, "r") as f:
                for _ in range(max_lines):
                    line = f.readline()
                    if not line:
                        break
                    preview.append(line.rstrip())
        except Exception:
            pass
        return preview

    def _extract_numeric_tokens(self, line):
        matches = re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", line)
        values = []
        for token in matches:
            try:
                values.append(float(token))
            except ValueError:
                pass
        return values

    def _read_ngspice_ac(self, path):
        """
        For the observed AC CSV format, the useful data is:
        - first column: frequency
        - last column: linear magnitude of output

        Example row:
        1E+00  1E+00  0E+00  1E+00  9.999995E-01

        We therefore use:
        x = nums[0]
        y = nums[-1]
        """
        xs = []
        ys = []

        with open(path, "r") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue

                nums = self._extract_numeric_tokens(line)
                if len(nums) < 2:
                    continue

                x = nums[0]
                y = nums[-1]

                xs.append(x)
                ys.append(y)

        return {"x": xs, "y": ys}

    def _read_wrdata_xy(self, path):
        """
        Parser for transient CSV-like wrdata output.
        Typical format observed:
        time  time  value

        We therefore use:
        x = first column
        y = last column
        """
        xs = []
        ys = []

        with open(path, "r") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue

                nums = self._extract_numeric_tokens(line)
                if len(nums) < 2:
                    continue

                x = nums[0]
                y = nums[-1]

                xs.append(x)
                ys.append(y)

        return {"x": xs, "y": ys}

    def _validate_xy_data(self, name, data, min_points=3, x_monotonic=False, x_positive=False):
        xs = list((data or {}).get("x") or [])
        ys = list((data or {}).get("y") or [])
        issues = []
        warnings = []

        if len(xs) != len(ys):
            issues.append(f"x/y length mismatch: {len(xs)} vs {len(ys)}.")

        points = min(len(xs), len(ys))
        if points < int(min_points):
            issues.append(f"Only {points} points found; expected at least {int(min_points)}.")

        finite_points = 0
        prev_x = None
        for idx in range(points):
            x = xs[idx]
            y = ys[idx]
            if not (math.isfinite(float(x)) and math.isfinite(float(y))):
                issues.append(f"Non-finite point encountered at index {idx}.")
                break
            finite_points += 1
            if x_positive and float(x) <= 0:
                issues.append("X-axis contains non-positive values where positive values are required.")
                break
            if x_monotonic and prev_x is not None and float(x) < float(prev_x):
                issues.append("X-axis is not monotonic non-decreasing.")
                break
            prev_x = x

        if points > 0 and finite_points == points:
            y_min = min(float(y) for y in ys[:points])
            y_max = max(float(y) for y in ys[:points])
            if abs(y_max - y_min) < 1e-15:
                warnings.append("Y-axis appears nearly constant; plot may be uninformative.")

        return {
            "name": name,
            "status": "pass" if not issues else "fail",
            "num_points": points,
            "issues": issues,
            "warnings": warnings,
        }

    def _validate_plot_file(self, name, path):
        issues = []
        warnings = []
        if not path:
            issues.append("Plot path was not set.")
            size_bytes = 0
        elif not os.path.exists(path):
            issues.append(f"Plot file not found at '{path}'.")
            size_bytes = 0
        else:
            size_bytes = os.path.getsize(path)
            if size_bytes < 200:
                issues.append(f"Plot file is unexpectedly small ({size_bytes} bytes).")
            elif size_bytes < 1000:
                warnings.append(f"Plot file is very small ({size_bytes} bytes); content may be incomplete.")

        return {
            "name": name,
            "status": "pass" if not issues else "fail",
            "num_points": None,
            "issues": issues,
            "warnings": warnings,
            "size_bytes": size_bytes,
        }

    def _summarize_plot_validations(self, validations):
        validations = list(validations or [])
        passes = sum(1 for item in validations if item.get("status") == "pass")
        fails = sum(1 for item in validations if item.get("status") == "fail")
        return {
            "passes": passes,
            "fails": fails,
            "overall_pass": fails == 0,
        }

    def _interpolate_x_for_target(self, x1, y1, x2, y2, target, log_x=False):
        x1 = float(x1)
        x2 = float(x2)
        y1 = float(y1)
        y2 = float(y2)
        target = float(target)

        if abs(y2 - y1) < 1e-30:
            return x2
        frac = (target - y1) / (y2 - y1)
        frac = max(0.0, min(1.0, frac))

        if log_x:
            lx1 = math.log10(max(x1, 1e-30))
            lx2 = math.log10(max(x2, 1e-30))
            return 10.0 ** (lx1 + frac * (lx2 - lx1))
        return x1 + frac * (x2 - x1)

    def _crossing_time(self, xs, ys, target, rising=True, start_index=1):
        xs = xs or []
        ys = ys or []
        if len(xs) < 2 or len(ys) < 2:
            return None

        start = max(1, int(start_index))
        for idx in range(start, min(len(xs), len(ys))):
            y_prev = float(ys[idx - 1])
            y_cur = float(ys[idx])
            crossed = (y_prev <= target <= y_cur) if rising else (y_prev >= target >= y_cur)
            if crossed:
                return self._interpolate_x_for_target(
                    xs[idx - 1],
                    y_prev,
                    xs[idx],
                    y_cur,
                    target,
                    log_x=False,
                )
        return None

    def _extract_gain_series_from_ac(self, data, input_ac_mag=1.0):
        xs = list(data.get("x", []) or [])
        ys = list(data.get("y", []) or [])
        if len(xs) < 2 or len(ys) < 2:
            return [], [], []

        input_ac_mag = max(float(input_ac_mag), 1e-20)
        gains = [max(abs(float(v)) / input_ac_mag, 1e-20) for v in ys]
        gains_db = [20.0 * math.log10(v) for v in gains]
        return xs, gains, gains_db

    def _edge_slope_db_per_dec(self, xs, gains_db, left=True):
        if len(xs) < 4 or len(gains_db) < 4:
            return None
        edge = max(2, len(xs) // 12)
        if left:
            i1 = 0
            i2 = edge
        else:
            i1 = len(xs) - edge - 1
            i2 = len(xs) - 1
        x1 = max(float(xs[i1]), 1e-30)
        x2 = max(float(xs[i2]), 1e-30)
        if abs(math.log10(x2) - math.log10(x1)) < 1e-12:
            return None
        return (float(gains_db[i2]) - float(gains_db[i1])) / (math.log10(x2) - math.log10(x1))

    def _characterize_ac_response(self, data, input_ac_mag=1.0):
        xs, gains, gains_db = self._extract_gain_series_from_ac(data, input_ac_mag=input_ac_mag)
        if len(xs) < 5:
            return {}

        n = len(xs)
        edge = max(3, n // 10)
        low_avg = sum(gains_db[:edge]) / edge
        high_avg = sum(gains_db[-edge:]) / edge
        peak_idx = max(range(n), key=lambda i: gains_db[i])
        peak_gain_db = float(gains_db[peak_idx])
        peak_hz = float(xs[peak_idx])
        min_gain_db = float(min(gains_db))
        target_3db = peak_gain_db - 3.0

        lower_3db = None
        for idx in range(peak_idx, 0, -1):
            y1 = gains_db[idx - 1]
            y2 = gains_db[idx]
            if (y1 <= target_3db <= y2) or (y1 >= target_3db >= y2):
                lower_3db = self._interpolate_x_for_target(xs[idx - 1], y1, xs[idx], y2, target_3db, log_x=True)
                break

        upper_3db = None
        for idx in range(peak_idx + 1, n):
            y1 = gains_db[idx - 1]
            y2 = gains_db[idx]
            if (y1 <= target_3db <= y2) or (y1 >= target_3db >= y2):
                upper_3db = self._interpolate_x_for_target(xs[idx - 1], y1, xs[idx], y2, target_3db, log_x=True)
                break

        response_shape = "bandpass"
        if peak_idx <= edge:
            response_shape = "lowpass"
        elif peak_idx >= (n - edge - 1):
            response_shape = "highpass"

        passband_slice = gains_db[:edge] if response_shape == "lowpass" else gains_db[-edge:]
        if response_shape == "bandpass":
            lo = max(0, peak_idx - edge // 2)
            hi = min(n, peak_idx + edge // 2 + 1)
            passband_slice = gains_db[lo:hi]
        passband_ripple = (max(passband_slice) - min(passband_slice)) if passband_slice else None

        result = {
            "response_shape": response_shape,
            "sample_points": n,
            "gain_low_db": float(low_avg),
            "gain_high_db": float(high_avg),
            "peak_gain_db": peak_gain_db,
            "peak_frequency_hz": peak_hz,
            "min_gain_db": min_gain_db,
            "passband_ripple_db": float(passband_ripple) if passband_ripple is not None else None,
            "resonance_peaking_db": peak_gain_db - max(float(low_avg), float(high_avg)),
            "slope_low_db_per_dec": self._edge_slope_db_per_dec(xs, gains_db, left=True),
            "slope_high_db_per_dec": self._edge_slope_db_per_dec(xs, gains_db, left=False),
            "lower_3db_hz": lower_3db,
            "upper_3db_hz": upper_3db,
        }

        if lower_3db is not None and upper_3db is not None and upper_3db > lower_3db:
            bw = upper_3db - lower_3db
            center = math.sqrt(max(lower_3db * upper_3db, 1e-30))
            result["estimated_bandwidth_hz"] = bw
            result["estimated_center_hz"] = center
            result["estimated_q"] = center / max(bw, 1e-30)
        elif response_shape in {"lowpass", "highpass"}:
            fc = upper_3db if response_shape == "lowpass" else lower_3db
            if fc is not None:
                result["estimated_cutoff_hz"] = fc

        return result

    def _characterize_step_response(self, tran_in_data, tran_out_data):
        tx = list((tran_out_data or {}).get("x") or [])
        vy = list((tran_out_data or {}).get("y") or [])
        in_y = list((tran_in_data or {}).get("y") or [])
        if len(tx) < 8 or len(vy) < 8:
            return {}

        n = min(len(tx), len(vy))
        edge = max(3, n // 20)
        out_initial = sum(float(v) for v in vy[:edge]) / edge
        out_final = sum(float(v) for v in vy[n - edge:n]) / edge
        out_delta = out_final - out_initial

        in_initial = None
        in_final = None
        in_delta = None
        if len(in_y) >= n:
            in_initial = sum(float(v) for v in in_y[:edge]) / edge
            in_final = sum(float(v) for v in in_y[n - edge:n]) / edge
            in_delta = in_final - in_initial

        direction_rising = out_delta >= 0
        t10 = self._crossing_time(tx, vy, out_initial + 0.10 * out_delta, rising=direction_rising)
        t90 = self._crossing_time(tx, vy, out_initial + 0.90 * out_delta, rising=direction_rising)

        tol = max(abs(out_delta) * 0.02, 1e-6)
        settling_time = None
        for idx in range(n):
            if all(abs(float(v) - out_final) <= tol for v in vy[idx:n]):
                settling_time = float(tx[idx]) - float(tx[0])
                break

        metrics = {
            "out_initial_v": out_initial,
            "out_final_v": out_final,
            "out_step_v": out_delta,
            "step_detected": abs(out_delta) > 1e-6,
            "settling_time_s": settling_time,
        }
        if in_initial is not None and in_final is not None and in_delta is not None:
            metrics["in_initial_v"] = in_initial
            metrics["in_final_v"] = in_final
            metrics["in_step_v"] = in_delta
            if abs(in_delta) > 1e-12:
                transient_gain_vv = out_delta / in_delta
                metrics["transient_gain_vv"] = transient_gain_vv
                metrics["transient_gain_db"] = 20.0 * math.log10(max(abs(transient_gain_vv), 1e-20))

        if t10 is not None and t90 is not None:
            interval = max(float(t90) - float(t10), 0.0)
            if direction_rising:
                metrics["rise_time_10_90_s"] = interval
            else:
                metrics["fall_time_90_10_s"] = interval

        out_max = max(float(v) for v in vy[:n])
        out_min = min(float(v) for v in vy[:n])
        if abs(out_delta) > 1e-9:
            if direction_rising:
                metrics["overshoot_pct"] = max(0.0, (out_max - out_final) / abs(out_delta) * 100.0)
                metrics["undershoot_pct"] = max(0.0, (out_initial - out_min) / abs(out_delta) * 100.0)
            else:
                metrics["overshoot_pct"] = max(0.0, (out_final - out_min) / abs(out_delta) * 100.0)
                metrics["undershoot_pct"] = max(0.0, (out_max - out_initial) / abs(out_delta) * 100.0)

        return metrics

    def _formula_fc_from_sizing(self, sizing):
        try:
            r = float(sizing.get("R_ohm", 0.0))
            c = float(sizing.get("C_f", 0.0))
        except Exception:
            return None

        if r <= 0 or c <= 0:
            return None

        return 1.0 / (2.0 * math.pi * r * c)

    def _plot_ac(self, data, out_path, input_ac_mag=1.0):
        """
        Input y-values are output magnitudes.
        Plot gain magnitude in dB so amplifier responses are not shown in dBV.
        """
        if not data["x"] or not data["y"]:
            return

        input_ac_mag = max(float(input_ac_mag), 1e-20)
        mags = [max(abs(v) / input_ac_mag, 1e-20) for v in data["y"]]
        mags_db = [20.0 * math.log10(v) for v in mags]

        plt = self._get_pyplot()
        if plt is not None:
            plt.figure(figsize=(8, 5))
            plt.semilogx(data["x"], mags_db)
            plt.xlabel("Frequency (Hz)")
            plt.ylabel("Gain (dB)")
            plt.title("AC Response |V(out)/V(in)|")
            plt.grid(True, which="both")
            plt.tight_layout()
            plt.savefig(out_path, dpi=160)
            plt.close()
            return

        transformed_x = [math.log10(max(x, 1e-30)) for x in data["x"]]
        self._write_svg_plot(
            out_path=out_path,
            x_values=transformed_x,
            y_series=[("Gain (dB)", mags_db, "#0f766e")],
            title="AC Response |V(out)/V(in)|",
            xlabel="log10(Frequency [Hz])",
            ylabel="Gain (dB)",
        )

    def _plot_tran(self, tran_in_data, tran_out_data, out_path):
        if not tran_out_data or not tran_out_data["x"] or not tran_out_data["y"]:
            return

        plt = self._get_pyplot()
        if plt is not None:
            plt.figure(figsize=(8, 5))

            if tran_in_data and tran_in_data["x"] and tran_in_data["y"]:
                plt.plot(tran_in_data["x"], tran_in_data["y"], label="V(in)")

            plt.plot(tran_out_data["x"], tran_out_data["y"], label="V(out)")
            plt.xlabel("Time (s)")
            plt.ylabel("Voltage (V)")
            plt.title("Transient Response")
            plt.grid(True)
            plt.legend()
            plt.tight_layout()
            plt.savefig(out_path, dpi=160)
            plt.close()
            return

        series = [("V(out)", tran_out_data["y"], "#1d4ed8")]
        if tran_in_data and tran_in_data["x"] and tran_in_data["y"]:
            series.insert(0, ("V(in)", tran_in_data["y"], "#dc2626"))

        self._write_svg_plot(
            out_path=out_path,
            x_values=tran_out_data["x"],
            y_series=series,
            title="Transient Response",
            xlabel="Time (s)",
            ylabel="Voltage (V)",
        )

    def _plot_tran_series(self, series_map, out_path):
        ordered = []
        palette = [
            "#dc2626",
            "#1d4ed8",
            "#0f766e",
            "#7c3aed",
            "#ea580c",
            "#0891b2",
        ]

        for label, data in series_map.items():
            if not data or not data.get("x") or not data.get("y"):
                continue
            ordered.append((label, data))

        if not ordered:
            return

        x_values = ordered[0][1]["x"]
        y_series = [
            (label, data["y"], palette[idx % len(palette)])
            for idx, (label, data) in enumerate(ordered)
        ]

        plt = self._get_pyplot()
        if plt is not None:
            plt.figure(figsize=(8, 5))
            for label, data in ordered:
                plt.plot(data["x"], data["y"], label=label)
            plt.xlabel("Time (s)")
            plt.ylabel("Voltage (V)")
            plt.title("Transient Response")
            plt.grid(True)
            plt.legend()
            plt.tight_layout()
            plt.savefig(out_path, dpi=160)
            plt.close()
            return

        self._write_svg_plot(
            out_path=out_path,
            x_values=x_values,
            y_series=y_series,
            title="Transient Response",
            xlabel="Time (s)",
            ylabel="Voltage (V)",
        )

    def _plot_dc(self, dc_data, out_path, xlabel="Input", ylabel="Output"):
        if not dc_data or not dc_data["x"] or not dc_data["y"]:
            return

        plt = self._get_pyplot()
        if plt is not None:
            plt.figure(figsize=(8, 5))
            plt.plot(dc_data["x"], dc_data["y"], label=ylabel)
            plt.xlabel(xlabel)
            plt.ylabel(ylabel)
            plt.title("DC Sweep")
            plt.grid(True)
            plt.legend()
            plt.tight_layout()
            plt.savefig(out_path, dpi=160)
            plt.close()
            return

        self._write_svg_plot(
            out_path=out_path,
            x_values=dc_data["x"],
            y_series=[(ylabel, dc_data["y"], "#7c3aed")],
            title="DC Sweep",
            xlabel=xlabel,
            ylabel=ylabel,
        )

    def _estimate_cutoff_from_ac(self, data):
        """
        Input y-values are linear magnitudes.
        For a first-order low-pass, cutoff is where magnitude drops to
        ref / sqrt(2).
        """
        xs = data.get("x", [])
        ys = data.get("y", [])

        if len(xs) < 3 or len(ys) < 3:
            return None

        mags = [max(abs(float(v)), 1e-20) for v in ys]
        ref = mags[0]
        if ref <= 0:
            return None

        target = ref / math.sqrt(2.0)

        for i in range(1, len(mags)):
            y1 = mags[i - 1]
            y2 = mags[i]
            x1 = xs[i - 1]
            x2 = xs[i]

            crossed = (y1 >= target and y2 <= target) or (y1 <= target and y2 >= target)
            if crossed:
                return self._interpolate_x_for_target(
                    x1,
                    y1,
                    x2,
                    y2,
                    target,
                    log_x=True,
                )

        idx = min(range(len(mags)), key=lambda i: abs(mags[i] - target))
        return xs[idx]

    def _estimate_highpass_cutoff_from_ac(self, data, input_ac_mag=1.0):
        xs, gains, _ = self._extract_gain_series_from_ac(data, input_ac_mag=input_ac_mag)
        if len(xs) < 3 or len(gains) < 3:
            return None

        ref = max(gains)
        target = ref / math.sqrt(2.0)

        for i in range(1, len(gains)):
            y1 = gains[i - 1]
            y2 = gains[i]
            if (y1 <= target <= y2) or (y1 >= target >= y2):
                return self._interpolate_x_for_target(
                    xs[i - 1],
                    y1,
                    xs[i],
                    y2,
                    target,
                    log_x=True,
                )

        idx = min(range(len(gains)), key=lambda i: abs(gains[i] - target))
        return xs[idx]

    def _estimate_bandpass_metrics_from_ac(self, data, input_ac_mag=1.0):
        xs, gains, gains_db = self._extract_gain_series_from_ac(data, input_ac_mag=input_ac_mag)
        if len(xs) < 5 or len(gains) < 5:
            return {}

        peak_idx = max(range(len(gains)), key=lambda i: gains[i])
        peak_gain = gains[peak_idx]
        peak_gain_db = gains_db[peak_idx]
        center_hz = xs[peak_idx]
        target = peak_gain / math.sqrt(2.0)

        lower = None
        for i in range(peak_idx, 0, -1):
            y1 = gains[i - 1]
            y2 = gains[i]
            if (y1 <= target <= y2) or (y1 >= target >= y2):
                lower = self._interpolate_x_for_target(
                    xs[i - 1],
                    y1,
                    xs[i],
                    y2,
                    target,
                    log_x=True,
                )
                break

        upper = None
        for i in range(peak_idx + 1, len(gains)):
            y1 = gains[i - 1]
            y2 = gains[i]
            if (y1 <= target <= y2) or (y1 >= target >= y2):
                upper = self._interpolate_x_for_target(
                    xs[i - 1],
                    y1,
                    xs[i],
                    y2,
                    target,
                    log_x=True,
                )
                break

        metrics = {
            "center_hz": center_hz,
            "peak_gain_db": peak_gain_db,
        }
        if lower is not None and upper is not None and upper > lower:
            bandwidth_hz = upper - lower
            metrics["bandwidth_hz"] = bandwidth_hz
            metrics["q_factor"] = center_hz / max(bandwidth_hz, 1e-30)
        return metrics

    def _extract_gain_bw_from_ac(self, data, input_ac_mag=1.0):
        xs, gains, gains_db = self._extract_gain_series_from_ac(data, input_ac_mag=input_ac_mag)
        if len(xs) < 3 or len(gains) < 3:
            return None, None

        gain0 = gains[0]
        gain0_db = gains_db[0]

        target = gain0 / math.sqrt(2.0)
        bw = None
        for i in range(1, len(gains)):
            y1 = gains[i - 1]
            y2 = gains[i]
            if (y1 >= target >= y2) or (y1 <= target <= y2):
                bw = self._interpolate_x_for_target(
                    xs[i - 1],
                    y1,
                    xs[i],
                    y2,
                    target,
                    log_x=True,
                )
                break

        return gain0_db, bw

    def _extract_unity_gain_bw_from_ac(self, data, input_ac_mag=1.0):
        xs, gains, _ = self._extract_gain_series_from_ac(data, input_ac_mag=input_ac_mag)
        if len(xs) < 3 or len(gains) < 3:
            return None

        for i in range(1, len(gains)):
            y1 = gains[i - 1]
            y2 = gains[i]
            if (y1 >= 1.0 >= y2) or (y1 <= 1.0 <= y2):
                return self._interpolate_x_for_target(
                    xs[i - 1],
                    y1,
                    xs[i],
                    y2,
                    1.0,
                    log_x=True,
                )
        return None
    
    def _extract_current_from_log(self, preview_lines):
        for line in preview_lines or []:
            match = re.search(
                r"(?:i\([^)]+\)|iop|iout)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
                line,
                re.IGNORECASE,
            )
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return None
        return None

    def _extract_named_voltage_from_log(self, preview_lines, token):
        token = token.lower()
        for line in preview_lines or []:
            line_lower = line.lower()
            if token not in line_lower:
                continue
            match = re.search(rf"{re.escape(token)}\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", line_lower)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return None
        return None

    def _extract_named_current_from_log(self, preview_lines, token):
        token = token.lower()
        for line in preview_lines or []:
            line_lower = line.lower()
            if token not in line_lower:
                continue
            match = re.search(rf"{re.escape(token)}\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", line_lower)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return None
        return None

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

    def _extract_op_region_summary(self, log_preview):
        if not log_preview:
            return []

        summary = []
        for line in log_preview:
            s = line.strip()
            if not s:
                continue
            if (
                "Node" in s
                or "Voltage" in s
                or "Current" in s
                or "@m1" in s
                or "v(out)" in s
                or "v(in)" in s
                or "Index" in s
            ):
                summary.append(s)

        return summary[:12]
    
    def _merged_constraints(self, memory):
        merged = {}
        merged.update(ANALOG_DEFAULTS.get("process", {}))
        merged.update(ANALOG_DEFAULTS.get("simulation", {}))
        merged.update(memory.read("constraints") or {})
        return merged

    def _last_value(self, data):
        if not data or not data.get("y"):
            return None
        try:
            return float(data["y"][-1])
        except Exception:
            return None

    def _estimate_oscillation_frequency(self, data):
        if not data:
            return None
        xs = data.get("x", [])
        ys = data.get("y", [])
        if len(xs) < 20 or len(ys) < 20:
            return None

        start_idx = len(xs) // 4
        crossings = []
        prev = ys[start_idx]
        for idx in range(start_idx + 1, len(ys)):
            cur = ys[idx]
            if prev <= 0 < cur:
                t1 = xs[idx - 1]
                t2 = xs[idx]
                y1 = prev
                y2 = cur
                if abs(y2 - y1) < 1e-30:
                    crossings.append(t2)
                else:
                    frac = (0 - y1) / (y2 - y1)
                    crossings.append(t1 + frac * (t2 - t1))
            prev = cur

        if len(crossings) < 2:
            return None

        periods = [crossings[i] - crossings[i - 1] for i in range(1, len(crossings)) if crossings[i] > crossings[i - 1]]
        if not periods:
            return None
        avg_period = sum(periods) / len(periods)
        if avg_period <= 0:
            return None
        return 1.0 / avg_period

    def _estimate_lc_formula_frequency(self, sizing):
        try:
            l_tank = float(sizing.get("L_tank", 0.0))
            c_tank = float(sizing.get("C_tank", 0.0))
        except Exception:
            return None
        if l_tank <= 0 or c_tank <= 0:
            return None
        return 1.0 / (2.0 * math.pi * math.sqrt(l_tank * c_tank))

    def _relative_error(self, measured, expected):
        if measured is None or expected is None:
            return None
        measured = float(measured)
        expected = float(expected)
        if abs(expected) < 1e-30:
            return None
        return abs(measured - expected) / abs(expected)

    def _check_metric(self, name, measured, target, rel_tol=0.15, abs_tol=None):
        check = {
            "name": name,
            "measured": measured,
            "target": target,
            "status": "unknown",
        }
        if measured is None or target is None:
            return check

        measured = float(measured)
        target = float(target)
        err = abs(measured - target)
        rel_err = err / max(abs(target), 1e-30)
        check["relative_error"] = rel_err
        check["absolute_error"] = err
        pass_rel = rel_err <= rel_tol
        pass_abs = abs_tol is not None and err <= abs_tol
        check["status"] = "pass" if (pass_rel or pass_abs) else "fail"
        return check

    def _build_verification_summary(self, topology, sizing, constraints, sim):
        target_checks = []
        analytical_checks = []

        for item in sim.get("plot_validations", []) or []:
            status = item.get("status")
            analytical_checks.append(
                {
                    "name": f"plot_validation::{item.get('name', 'unknown')}",
                    "measured": status,
                    "target": "pass",
                    "status": "pass" if status == "pass" else ("fail" if status == "fail" else "unknown"),
                    "issues": item.get("issues") or [],
                    "warnings": item.get("warnings") or [],
                }
            )

        gm_id_est = sizing.get("gm_id_est_s_per_a")
        gm_id_target = sizing.get("gm_id_target_s_per_a")
        if gm_id_est is not None and gm_id_target is not None:
            analytical_checks.append(
                self._check_metric(
                    "gm_id_estimate_s_per_a",
                    gm_id_est,
                    gm_id_target,
                    rel_tol=0.35,
                    abs_tol=4.0,
                )
            )
        if sizing.get("ro_est_ohm") is not None and sizing.get("gm_est_s") is not None:
            analytical_checks.append(
                {
                    "name": "intrinsic_gain_estimate_vv",
                    "measured": float(sizing["gm_est_s"]) * float(sizing["ro_est_ohm"]),
                    "target": None,
                    "status": "informational",
                }
            )

        def boolean_check(name, measured, target=True):
            return {
                "name": name,
                "measured": measured,
                "target": target,
                "status": "pass" if measured is target else ("fail" if measured is not None else "unknown"),
            }

        if topology == "rc_lowpass":
            target_checks.append(self._check_metric("cutoff_hz", sim.get("fc_hz"), constraints.get("target_fc_hz"), rel_tol=0.08))
            analytical_checks.append(self._check_metric("cutoff_vs_formula", sim.get("fc_hz"), self._formula_fc_from_sizing(sizing), rel_tol=0.08))

        elif topology in {"rlc_lowpass_2nd_order", "rlc_highpass_2nd_order"}:
            target_checks.append(self._check_metric("cutoff_hz", sim.get("fc_hz"), constraints.get("target_fc_hz"), rel_tol=0.12))
            analytical_checks.append(self._check_metric("q_factor", sim.get("q_factor"), sizing.get("q_target"), rel_tol=0.35))

            ac_char = sim.get("ac_characterization") or {}
            low_db = ac_char.get("gain_low_db")
            high_db = ac_char.get("gain_high_db")
            trend_pass = None
            if low_db is not None and high_db is not None:
                if topology == "rlc_lowpass_2nd_order":
                    trend_pass = float(low_db) > float(high_db)
                else:
                    trend_pass = float(high_db) > float(low_db)
            analytical_checks.append(
                {
                    "name": "passband_trend",
                    "measured": trend_pass,
                    "target": True,
                    "status": "pass" if trend_pass is True else ("fail" if trend_pass is False else "unknown"),
                }
            )

        elif topology == "rlc_bandpass_2nd_order":
            target_checks.append(self._check_metric("center_hz", sim.get("center_hz"), constraints.get("target_center_hz"), rel_tol=0.15))
            target_checks.append(self._check_metric("bandwidth_hz", sim.get("bandwidth_hz"), constraints.get("target_bw_hz"), rel_tol=0.25))
            analytical_checks.append(self._check_metric("q_factor", sim.get("q_factor"), sizing.get("q_target"), rel_tol=0.35))
            ac_char = sim.get("ac_characterization") or {}
            shape_measured = ac_char.get("response_shape")
            analytical_checks.append(
                {
                    "name": "response_shape",
                    "measured": shape_measured,
                    "target": "bandpass",
                    "status": "pass" if shape_measured == "bandpass" else ("fail" if shape_measured is not None else "unknown"),
                }
            )

        elif topology in {"current_mirror", "wilson_current_mirror", "cascode_current_mirror", "widlar_current_mirror"}:
            mirror_tol = 0.30 if topology == "wilson_current_mirror" else 0.10
            target_checks.append(self._check_metric("iout_a", sim.get("iout_a"), constraints.get("target_iout_a"), rel_tol=mirror_tol))
            analytical_checks.append(
                self._check_metric(
                    "iout_vs_sizing",
                    sim.get("iout_a"),
                    sizing.get("I_out_target", constraints.get("target_iout_a")),
                    rel_tol=mirror_tol,
                )
            )

        elif topology in {
            "common_source_res_load",
            "source_degenerated_cs",
            "common_source_active_load",
            "diode_connected_stage",
            "cascode_amplifier",
            "common_drain",
            "common_gate",
        }:
            gm_est = None
            if sizing.get("I_bias") is not None:
                vov = sizing.get("Vov_target", constraints.get("target_vov_v", 0.2))
                gm_est = 2.0 * float(sizing["I_bias"]) / max(float(vov), 1e-12)
            gain_est_db = None
            if gm_est is not None:
                if topology in {"common_source_res_load", "source_degenerated_cs", "common_gate", "cascode_amplifier"}:
                    r_eff = float(sizing.get("R_D", 1.0))
                    gain_est_db = 20.0 * math.log10(max(gm_est * r_eff, 1e-20))
                elif topology == "common_drain":
                    gain_est_db = 20.0 * math.log10(max(gm_est * float(sizing.get("R_source", 1.0)) / (1.0 + gm_est * float(sizing.get("R_source", 1.0))), 1e-20))
            target_checks.append(self._check_metric("gain_db", sim.get("gain_db"), constraints.get("target_gain_db"), rel_tol=0.20, abs_tol=2.0))
            target_checks.append(self._check_metric("power_mw", sim.get("power_mw"), constraints.get("power_limit_mw"), rel_tol=0.0, abs_tol=0.0))
            if target_checks[-1]["status"] != "unknown":
                target_checks[-1]["status"] = "pass" if float(sim.get("power_mw", 1e30)) <= float(constraints.get("power_limit_mw")) else "fail"
            analytical_checks.append(self._check_metric("gain_vs_first_order_estimate", sim.get("gain_db"), gain_est_db, rel_tol=0.30, abs_tol=4.0))

        elif topology == "diff_pair":
            target_checks.append(self._check_metric("power_mw", sim.get("power_mw"), constraints.get("power_limit_mw"), rel_tol=0.0, abs_tol=0.0))
            if target_checks[-1]["status"] != "unknown":
                target_checks[-1]["status"] = "pass" if float(sim.get("power_mw", 1e30)) <= float(constraints.get("power_limit_mw")) else "fail"
            if sim.get("gain_db") is not None:
                gain_floor = float(constraints.get("min_gain_db", 6.0))
                target_checks.append({
                    "name": "gain_floor_db",
                    "measured": sim.get("gain_db"),
                    "target": gain_floor,
                    "status": "pass" if float(sim.get("gain_db")) >= gain_floor else "fail",
                })
            tail_current = sizing.get("I_tail")
            rload = sizing.get("R_load")
            vov = sizing.get("Vov_target", constraints.get("target_vov_v", 0.2))
            if tail_current is not None and rload is not None and vov is not None:
                gm_half = float(tail_current) / max(2.0 * float(vov), 1e-12)
                gain_est_db = 20.0 * math.log10(max(gm_half * float(rload), 1e-20))
                analytical_checks.append(self._check_metric("gain_vs_half_circuit_estimate", sim.get("gain_db"), gain_est_db, rel_tol=0.35, abs_tol=4.0))

        elif topology == "bjt_diff_pair":
            target_checks.append(self._check_metric("gain_db", sim.get("gain_db"), constraints.get("target_gain_db"), rel_tol=0.30, abs_tol=4.0))
            analytical_checks.append(self._check_metric("bandwidth_hz", sim.get("bandwidth_hz"), constraints.get("target_bw_hz"), rel_tol=0.35))

        elif topology == "gm_stage":
            gm_measured = (((sim.get("device_metrics") or {}).get("m1") or {}).get("gm"))
            target_checks.append(self._check_metric("gm_s", gm_measured, constraints.get("target_gm_s"), rel_tol=0.25))
            if sim.get("gain_db") is not None:
                analytical_checks.append(
                    {
                        "name": "gain_metric_present",
                        "measured": sim.get("gain_db"),
                        "target": "available",
                        "status": "pass",
                    }
                )

        elif topology in {"two_stage_miller", "folded_cascode_opamp"}:
            target_checks.append(self._check_metric("gain_db", sim.get("gain_db"), constraints.get("target_gain_db"), rel_tol=0.20, abs_tol=8.0))
            target_checks.append(self._check_metric("ugbw_hz", sim.get("ugbw_hz"), constraints.get("target_ugbw_hz"), rel_tol=1.10))
            if constraints.get("power_limit_mw") is not None:
                check = self._check_metric("power_mw", sim.get("power_mw"), constraints.get("power_limit_mw"), rel_tol=0.0, abs_tol=0.0)
                if check["status"] != "unknown":
                    check["status"] = "pass" if float(sim.get("power_mw", 1e30)) <= float(constraints.get("power_limit_mw")) else "fail"
                target_checks.append(check)
            expected_ugbw = None
            gm1 = sizing.get("gm1_target_s")
            cload = constraints.get("load_cap_f")
            if gm1 is not None and cload is not None and float(cload) > 0:
                expected_ugbw = float(gm1) / (2.0 * math.pi * float(cload))
            analytical_checks.append(self._check_metric("ugbw_vs_gm_cl", sim.get("ugbw_hz"), expected_ugbw, rel_tol=1.10))
            if topology == "two_stage_miller":
                analytical_checks.append(
                    self._check_metric(
                        "transient_gain_vs_ac_gain_db",
                        sim.get("transient_gain_db"),
                        sim.get("gain_db"),
                        rel_tol=0.70,
                        abs_tol=40.0,
                    )
                )

        elif topology == "bandgap_reference_core":
            target_checks.append(self._check_metric("vref_v", sim.get("vref_v"), constraints.get("target_vref_v"), rel_tol=0.08, abs_tol=0.06))

        elif topology == "nand2_cmos":
            vdd = constraints.get("supply_v")
            vhigh = sim.get("logic_high_v")
            vlow = sim.get("logic_low_v")
            if vdd is not None and vhigh is not None:
                target_checks.append(
                    {
                        "name": "logic_high_margin",
                        "measured": vhigh,
                        "target": 0.8 * float(vdd),
                        "status": "pass" if float(vhigh) >= 0.8 * float(vdd) else "fail",
                    }
                )
            if vdd is not None and vlow is not None:
                target_checks.append(
                    {
                        "name": "logic_low_margin",
                        "measured": vlow,
                        "target": 0.2 * float(vdd),
                        "status": "pass" if float(vlow) <= 0.2 * float(vdd) else "fail",
                    }
                )

        elif topology == "sram6t_cell":
            target_checks.append(boolean_check("write_ok", sim.get("write_ok"), target=True))

        elif topology == "lc_oscillator_cross_coupled":
            target_checks.append(self._check_metric("oscillation_hz", sim.get("oscillation_hz"), constraints.get("target_osc_hz"), rel_tol=0.45))
            analytical_checks.append(self._check_metric("oscillation_vs_lc_formula", sim.get("oscillation_hz"), self._estimate_lc_formula_frequency(sizing), rel_tol=0.50))

        elif topology == "comparator":
            measured = sim.get("decision_delay_s")
            target = constraints.get("target_decision_delay_s")
            if target is not None:
                check = self._check_metric("decision_delay_s", measured, target, rel_tol=0.30)
                if check["status"] != "unknown":
                    check["status"] = "pass" if measured <= target else "fail"
                target_checks.append(check)
            analytical_checks.append(boolean_check("decision_correct", sim.get("decision_correct"), target=True))

        elif topology == "composite_pipeline":
            target_checks.append(
                self._check_metric(
                    "gain_db",
                    sim.get("gain_db"),
                    constraints.get("target_gain_db"),
                    rel_tol=0.30,
                    abs_tol=4.0,
                )
            )
            target_checks.append(
                self._check_metric(
                    "bandwidth_hz",
                    sim.get("bandwidth_hz"),
                    constraints.get("target_bw_hz"),
                    rel_tol=0.35,
                )
            )
            if constraints.get("power_limit_mw") is not None:
                power_check = self._check_metric(
                    "power_mw",
                    sim.get("power_mw"),
                    constraints.get("power_limit_mw"),
                    rel_tol=0.0,
                    abs_tol=0.0,
                )
                if power_check["status"] != "unknown":
                    power_check["status"] = (
                        "pass"
                        if float(sim.get("power_mw", 1e30)) <= float(constraints.get("power_limit_mw"))
                        else "fail"
                    )
                target_checks.append(power_check)
            stage_count = sizing.get("stage_count")
            if stage_count is not None:
                analytical_checks.append(
                    {
                        "name": "stage_count_present",
                        "measured": stage_count,
                        "target": ">=2",
                        "status": "pass" if float(stage_count) >= 2 else "fail",
                    }
                )
            if sizing.get("estimated_total_gain_db") is not None and sim.get("gain_db") is not None:
                analytical_checks.append(
                    self._check_metric(
                        "gain_vs_stage_estimate_db",
                        sim.get("gain_db"),
                        sizing.get("estimated_total_gain_db"),
                        rel_tol=0.40,
                        abs_tol=15.0,
                    )
                )
            stage_report = sim.get("netlist_stage_report") or {}
            if stage_report:
                for key, check_name in (
                    ("stage_count_match", "composite_stage_count_match"),
                    ("topology_order_match", "composite_stage_order_match"),
                ):
                    if stage_report.get(key) is not None:
                        analytical_checks.append(
                            boolean_check(check_name, stage_report.get(key), target=True)
                        )
                continuity_issues = stage_report.get("continuity_issues") or []
                analytical_checks.append(
                    {
                        "name": "composite_interstage_continuity",
                        "measured": len(continuity_issues),
                        "target": 0,
                        "status": "pass" if len(continuity_issues) == 0 else "fail",
                        "issues": continuity_issues,
                    }
                )

        passes = sum(1 for item in target_checks + analytical_checks if item.get("status") == "pass")
        fails = sum(1 for item in target_checks + analytical_checks if item.get("status") == "fail")
        unknown = sum(1 for item in target_checks + analytical_checks if item.get("status") == "unknown")
        total_checks = len(target_checks) + len(analytical_checks)
        known_checks = passes + fails
        return {
            "target_checks": target_checks,
            "analytical_checks": analytical_checks,
            "passes": passes,
            "fails": fails,
            "unknown": unknown,
            "total_checks": total_checks,
            "known_checks": known_checks,
            "coverage_ratio": (known_checks / total_checks) if total_checks > 0 else 0.0,
            "overall_pass": fails == 0,
        }

    def _extract_comparator_metrics(self, tran_in_data, tran_out_data, supply_v):
        metrics = {}
        if not tran_in_data or not tran_out_data:
            return metrics
        tin = tran_in_data.get("x", [])
        vin = tran_in_data.get("y", [])
        tout = tran_out_data.get("x", [])
        vout = tran_out_data.get("y", [])
        if len(tin) < 2 or len(vin) < 2 or len(tout) < 2 or len(vout) < 2:
            return metrics

        threshold_in = 0.5 * (max(vin) + min(vin))
        threshold_out = 0.5 * float(supply_v)
        t_in_cross = self._crossing_time(tin, vin, threshold_in, rising=True)

        t_out_cross = None
        if t_in_cross is not None:
            start_idx = 1
            while start_idx < len(tout) and float(tout[start_idx]) < float(t_in_cross):
                start_idx += 1
            for idx in range(max(1, start_idx), len(vout)):
                y1 = float(vout[idx - 1])
                y2 = float(vout[idx])
                crossed = (y1 - threshold_out) * (y2 - threshold_out) <= 0
                if crossed:
                    t_out_cross = self._interpolate_x_for_target(
                        tout[idx - 1],
                        y1,
                        tout[idx],
                        y2,
                        threshold_out,
                        log_x=False,
                    )
                    break
        if t_in_cross is not None and t_out_cross is not None:
            delay = float(t_out_cross) - float(t_in_cross)
            if delay >= -1e-12:
                metrics["decision_delay_s"] = max(delay, 0.0)
        if vout:
            metrics["decision_correct"] = max(vout) > threshold_out
        return metrics

    def _write_svg_plot(self, out_path, x_values, y_series, title, xlabel, ylabel):
        width = 960
        height = 540
        margin_left = 80
        margin_right = 24
        margin_top = 52
        margin_bottom = 68
        plot_width = width - margin_left - margin_right
        plot_height = height - margin_top - margin_bottom

        finite_x = [float(x) for x in x_values if x is not None]
        finite_y = [
            float(value)
            for _, values, _ in y_series
            for value in values
            if value is not None
        ]
        if len(finite_x) < 2 or len(finite_y) < 2:
            return

        x_min = min(finite_x)
        x_max = max(finite_x)
        y_min = min(finite_y)
        y_max = max(finite_y)

        if abs(x_max - x_min) < 1e-30:
            x_max = x_min + 1.0
        if abs(y_max - y_min) < 1e-30:
            y_max = y_min + 1.0

        def scale_x(x):
            return margin_left + (float(x) - x_min) / (x_max - x_min) * plot_width

        def scale_y(y):
            return margin_top + (1.0 - (float(y) - y_min) / (y_max - y_min)) * plot_height

        def axis_ticks(vmin, vmax, count=5):
            step = (vmax - vmin) / max(count - 1, 1)
            return [vmin + idx * step for idx in range(count)]

        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#fcfcfd"/>',
            f'<text x="{width / 2:.1f}" y="28" text-anchor="middle" font-size="20" font-family="Arial, sans-serif" fill="#111827">{escape(title)}</text>',
            f'<line x1="{margin_left}" y1="{margin_top + plot_height}" x2="{margin_left + plot_width}" y2="{margin_top + plot_height}" stroke="#111827" stroke-width="1.2"/>',
            f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}" stroke="#111827" stroke-width="1.2"/>',
        ]

        for x_tick in axis_ticks(x_min, x_max):
            x_pos = scale_x(x_tick)
            lines.append(
                f'<line x1="{x_pos:.2f}" y1="{margin_top}" x2="{x_pos:.2f}" y2="{margin_top + plot_height}" stroke="#e5e7eb" stroke-width="1"/>'
            )
            lines.append(
                f'<text x="{x_pos:.2f}" y="{height - 28}" text-anchor="middle" font-size="11" font-family="Arial, sans-serif" fill="#374151">{x_tick:.3g}</text>'
            )

        for y_tick in axis_ticks(y_min, y_max):
            y_pos = scale_y(y_tick)
            lines.append(
                f'<line x1="{margin_left}" y1="{y_pos:.2f}" x2="{margin_left + plot_width}" y2="{y_pos:.2f}" stroke="#e5e7eb" stroke-width="1"/>'
            )
            lines.append(
                f'<text x="{margin_left - 10}" y="{y_pos + 4:.2f}" text-anchor="end" font-size="11" font-family="Arial, sans-serif" fill="#374151">{y_tick:.3g}</text>'
            )

        legend_x = margin_left + 8
        legend_y = margin_top - 18
        for idx, (label, values, color) in enumerate(y_series):
            points = []
            for x, y in zip(x_values, values):
                if x is None or y is None:
                    continue
                points.append(f"{scale_x(x):.2f},{scale_y(y):.2f}")
            if len(points) >= 2:
                lines.append(
                    f'<polyline fill="none" stroke="{color}" stroke-width="2.2" points="{" ".join(points)}"/>'
                )
            label_y = legend_y + idx * 18
            lines.append(
                f'<line x1="{legend_x}" y1="{label_y}" x2="{legend_x + 18}" y2="{label_y}" stroke="{color}" stroke-width="3"/>'
            )
            lines.append(
                f'<text x="{legend_x + 24}" y="{label_y + 4}" font-size="12" font-family="Arial, sans-serif" fill="#111827">{escape(label)}</text>'
            )

        lines.extend(
            [
                f'<text x="{width / 2:.1f}" y="{height - 8}" text-anchor="middle" font-size="13" font-family="Arial, sans-serif" fill="#111827">{escape(xlabel)}</text>',
                f'<text x="20" y="{height / 2:.1f}" text-anchor="middle" font-size="13" font-family="Arial, sans-serif" fill="#111827" transform="rotate(-90 20 {height / 2:.1f})">{escape(ylabel)}</text>',
                "</svg>",
            ]
        )

        with open(out_path, "w") as f:
            f.write("\n".join(lines))
