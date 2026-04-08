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
        "rc_lowpass",
        "rlc_lowpass_2nd_order",
        "rlc_highpass_2nd_order",
        "rlc_bandpass_2nd_order",
        "common_source_res_load",
        "diff_pair",
        "two_stage_miller",
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

        with tempfile.TemporaryDirectory() as tmpdir:
            netlist_path = os.path.join(tmpdir, "generated.sp")
            with open(netlist_path, "w") as f:
                f.write(netlist)

            saved_netlist_path = os.path.join(base_dir, "generated.sp")
            with open(saved_netlist_path, "w") as f:
                f.write(netlist)

            result = subprocess.run(
                [self.ngspice_path, "-b", "-o", "ngspice.log", netlist_path],
                cwd=tmpdir,
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
            }

            self._safe_write_text(os.path.join(base_dir, "stdout.txt"), result.stdout or "")
            self._safe_write_text(os.path.join(base_dir, "stderr.txt"), result.stderr or "")

            log_path = os.path.join(tmpdir, "ngspice.log")
            if os.path.exists(log_path):
                shutil.copy2(log_path, os.path.join(base_dir, "ngspice.log"))

            if result.returncode != 0:
                memory.write("simulation_results", sim)
                memory.write("status", DesignStatus.SIMULATION_FAILED)
                return sim

            ac_csv = os.path.join(tmpdir, "ac_out.csv")
            dc_csv = os.path.join(tmpdir, "dc_out.csv")
            tran_in_csv = os.path.join(tmpdir, "tran_in.csv")
            tran_out_csv = os.path.join(tmpdir, "tran_out.csv")

            # -------------------------
            # AC artifacts
            # -------------------------
            if os.path.exists(ac_csv):
                saved_ac_csv = os.path.join(base_dir, "ac_out.csv")
                shutil.copy2(ac_csv, saved_ac_csv)

                sim["ac_csv"] = saved_ac_csv
                sim["ac_preview"] = self._preview_file(saved_ac_csv, max_lines=8)

                ac_data = self._read_ngspice_ac(saved_ac_csv)

                if ac_data["x"] and ac_data["y"]:
                    sim["ac_points"] = len(ac_data["x"])
                    ac_plot = os.path.join(base_dir, "ac_plot.svg")
                    input_ac_mag = float(constraints.get("vin_ac", 1.0))
                    if topology == "diff_pair":
                        input_ac_mag *= 2.0
                    self._plot_ac(ac_data, ac_plot, input_ac_mag=input_ac_mag)
                    sim["ac_plot"] = ac_plot
                    gain_db, bw_hz = self._extract_gain_bw_from_ac(ac_data, input_ac_mag=input_ac_mag)
                    
                    if gain_db is not None: 
                        sim["gain_db"] = gain_db 
                    if bw_hz is not None: 
                        sim["bandwidth_hz"] = bw_hz

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
                saved_dc_csv = os.path.join(base_dir, "dc_out.csv")
                shutil.copy2(dc_csv, saved_dc_csv)
                sim["dc_csv"] = saved_dc_csv
                sim["dc_preview"] = self._preview_file(saved_dc_csv, max_lines=8)

                dc_data = self._read_wrdata_xy(saved_dc_csv)
                if dc_data["x"] and dc_data["y"]:
                    sim["dc_points"] = len(dc_data["x"])
                    dc_plot = os.path.join(base_dir, "dc_plot.svg")
                    self._plot_dc(dc_data, dc_plot, xlabel="Sweep Variable", ylabel="Output")
                    sim["dc_plot"] = dc_plot

            # -------------------------
            # Transient artifacts
            # -------------------------
            tran_series = {}
            tran_in_data = None
            tran_out_data = None
            tran_qb_data = None
            tran_diff_data = None

            if os.path.exists(tran_in_csv):
                saved_tran_in_csv = os.path.join(base_dir, "tran_in.csv")
                shutil.copy2(tran_in_csv, saved_tran_in_csv)
                sim["tran_in_csv"] = saved_tran_in_csv
                tran_in_data = self._read_wrdata_xy(saved_tran_in_csv)
                tran_series["V(in)"] = tran_in_data

            if os.path.exists(tran_out_csv):
                saved_tran_out_csv = os.path.join(base_dir, "tran_out.csv")
                shutil.copy2(tran_out_csv, saved_tran_out_csv)
                sim["tran_out_csv"] = saved_tran_out_csv
                sim["tran_preview"] = self._preview_file(saved_tran_out_csv, max_lines=5)
                tran_out_data = self._read_wrdata_xy(saved_tran_out_csv)
                tran_series["V(out)"] = tran_out_data

            extra_tran_specs = [
                ("tran_in_a.csv", "tran_in_a_csv", "V(in_a)"),
                ("tran_in_b.csv", "tran_in_b_csv", "V(in_b)"),
                ("tran_bl.csv", "tran_bl_csv", "V(BL)"),
                ("tran_blb.csv", "tran_blb_csv", "V(BLB)"),
                ("tran_wl.csv", "tran_wl_csv", "V(WL)"),
                ("tran_outn.csv", "tran_outn_csv", "V(outn)"),
            ]
            for filename, sim_key, label in extra_tran_specs:
                candidate = os.path.join(tmpdir, filename)
                if os.path.exists(candidate):
                    saved_candidate = os.path.join(base_dir, filename)
                    shutil.copy2(candidate, saved_candidate)
                    sim[sim_key] = saved_candidate
                    tran_series[label] = self._read_wrdata_xy(saved_candidate)

            tran_qb_csv = os.path.join(tmpdir, "tran_qb.csv")
            if os.path.exists(tran_qb_csv):
                saved_tran_qb_csv = os.path.join(base_dir, "tran_qb.csv")
                shutil.copy2(tran_qb_csv, saved_tran_qb_csv)
                sim["tran_qb_csv"] = saved_tran_qb_csv
                tran_qb_data = self._read_wrdata_xy(saved_tran_qb_csv)
                tran_series["V(QB)"] = tran_qb_data

            tran_diff_csv = os.path.join(tmpdir, "tran_diff.csv")
            if os.path.exists(tran_diff_csv):
                saved_tran_diff_csv = os.path.join(base_dir, "tran_diff.csv")
                shutil.copy2(tran_diff_csv, saved_tran_diff_csv)
                sim["tran_diff_csv"] = saved_tran_diff_csv
                tran_diff_data = self._read_wrdata_xy(saved_tran_diff_csv)
                tran_series["V(outp,outn)"] = tran_diff_data

            if tran_out_data and tran_out_data["x"] and tran_out_data["y"]:
                tran_plot = os.path.join(base_dir, "tran_plot.svg")
                self._plot_tran_series(tran_series, tran_plot)
                sim["tran_plot"] = tran_plot
                sim["tran_points"] = len(tran_out_data["x"])
            
            if os.path.exists(log_path):
                saved_log = os.path.join(base_dir, "ngspice.log")
                shutil.copy2(log_path, saved_log)
                sim["log_path"] = saved_log
                sim["log_preview"] = self._preview_file(saved_log, max_lines=20)

                if topology == "current_mirror":
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
                sim["q_factor"] = sim.get("q_factor") or sizing.get("q_target")
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

        mags = [abs(v) for v in ys]
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
                if abs(y2 - y1) < 1e-30:
                    return x2
                frac = (target - y1) / (y2 - y1)
                return x1 + frac * (x2 - x1)

        idx = min(range(len(mags)), key=lambda i: abs(mags[i] - target))
        return xs[idx]

    def _estimate_highpass_cutoff_from_ac(self, data, input_ac_mag=1.0):
        xs = data.get("x", [])
        ys = data.get("y", [])
        if len(xs) < 3 or len(ys) < 3:
            return None

        input_ac_mag = max(float(input_ac_mag), 1e-20)
        gains = [max(abs(v) / input_ac_mag, 1e-20) for v in ys]
        ref = max(gains)
        target = ref / math.sqrt(2.0)

        for i in range(1, len(gains)):
            if gains[i - 1] <= target <= gains[i]:
                return xs[i]

        idx = min(range(len(gains)), key=lambda i: abs(gains[i] - target))
        return xs[idx]

    def _estimate_bandpass_metrics_from_ac(self, data, input_ac_mag=1.0):
        xs = data.get("x", [])
        ys = data.get("y", [])
        if len(xs) < 5 or len(ys) < 5:
            return {}

        input_ac_mag = max(float(input_ac_mag), 1e-20)
        gains = [max(abs(v) / input_ac_mag, 1e-20) for v in ys]
        peak_idx = max(range(len(gains)), key=lambda i: gains[i])
        peak_gain = gains[peak_idx]
        peak_gain_db = 20.0 * math.log10(max(peak_gain, 1e-20))
        center_hz = xs[peak_idx]
        target = peak_gain / math.sqrt(2.0)

        lower = None
        for i in range(peak_idx, 0, -1):
            if gains[i - 1] <= target <= gains[i]:
                lower = xs[i]
                break

        upper = None
        for i in range(peak_idx + 1, len(gains)):
            if gains[i] <= target <= gains[i - 1]:
                upper = xs[i]
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
        xs = data.get("x", [])
        ys = data.get("y", [])
        if len(xs) < 3 or len(ys) < 3:
            return None, None

        input_ac_mag = max(float(input_ac_mag), 1e-20)

        gains = [max(abs(v) / input_ac_mag, 1e-20) for v in ys]
        gain0 = gains[0]
        gain0_db = 20.0 * math.log10(gain0)

        target = gain0 / math.sqrt(2.0)
        bw = None
        for i in range(1, len(gains)):
            if gains[i - 1] >= target and gains[i] <= target:
                bw = xs[i]
                break

        return gain0_db, bw
    
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
