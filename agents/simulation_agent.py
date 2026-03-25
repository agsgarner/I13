# I13/agents/simulation_agent.py

import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime

import matplotlib.pyplot as plt

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory


class SimulationAgent(BaseAgent):
    def __init__(self, llm=None, ngspice_path=None, max_retries=1, wait=0):
        super().__init__(llm=llm, max_retries=max_retries, wait=wait)
        self.ngspice_path = ngspice_path or os.getenv("NGSPICE_PATH") or self._find_ngspice()

    def run_agent(self, memory: SharedMemory):
        netlist = memory.read("netlist")
        topology = memory.read("selected_topology")
        sizing = memory.read("sizing") or {}

        if not netlist:
            memory.write("status", "simulation_failed")
            memory.write("simulation_error", "Missing netlist")
            return None

        if not self.ngspice_path:
            memory.write("status", "simulation_failed")
            memory.write("simulation_error", "ngspice not found")
            return None

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.join("artifacts", "simulations", run_id)
        os.makedirs(base_dir, exist_ok=True)

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
            }

            self._safe_write_text(os.path.join(base_dir, "stdout.txt"), result.stdout or "")
            self._safe_write_text(os.path.join(base_dir, "stderr.txt"), result.stderr or "")

            log_path = os.path.join(tmpdir, "ngspice.log")
            if os.path.exists(log_path):
                shutil.copy2(log_path, os.path.join(base_dir, "ngspice.log"))

            if result.returncode != 0:
                memory.write("simulation_results", sim)
                memory.write("status", "simulation_failed")
                return sim

            ac_csv = os.path.join(tmpdir, "ac_out.csv")
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
                    ac_plot = os.path.join(base_dir, "ac_plot.png")
                    self._plot_ac(ac_data, ac_plot)
                    sim["ac_plot"] = ac_plot

                    if topology == "rc_lowpass":
                        sim["fc_hz_from_ac"] = self._estimate_cutoff_from_ac(ac_data)
                else:
                    sim["parser_warning"] = (
                        "AC file was created, but parser could not extract usable AC points."
                    )
            else:
                sim["parser_warning"] = (
                    "ac_out.csv was not created by ngspice; using formula-based cutoff."
                )

            # -------------------------
            # Transient artifacts
            # -------------------------
            tran_in_data = None
            tran_out_data = None

            if os.path.exists(tran_in_csv):
                saved_tran_in_csv = os.path.join(base_dir, "tran_in.csv")
                shutil.copy2(tran_in_csv, saved_tran_in_csv)
                sim["tran_in_csv"] = saved_tran_in_csv
                tran_in_data = self._read_wrdata_xy(saved_tran_in_csv)

            if os.path.exists(tran_out_csv):
                saved_tran_out_csv = os.path.join(base_dir, "tran_out.csv")
                shutil.copy2(tran_out_csv, saved_tran_out_csv)
                sim["tran_out_csv"] = saved_tran_out_csv
                sim["tran_preview"] = self._preview_file(saved_tran_out_csv, max_lines=5)
                tran_out_data = self._read_wrdata_xy(saved_tran_out_csv)

            if tran_out_data and tran_out_data["x"] and tran_out_data["y"]:
                tran_plot = os.path.join(base_dir, "tran_plot.png")
                self._plot_tran(tran_in_data, tran_out_data, tran_plot)
                sim["tran_plot"] = tran_plot
                sim["tran_points"] = len(tran_out_data["x"])

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

            memory.write("simulation_results", sim)
            memory.write("status", "simulation_complete")
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

    def _safe_write_text(self, path, text):
        with open(path, "w") as f:
            f.write(text)

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

    def _plot_ac(self, data, out_path):
        """
        Input y-values are linear magnitudes, not dB.
        Convert to dB for plotting.
        """
        if not data["x"] or not data["y"]:
            return

        mags = [max(abs(v), 1e-20) for v in data["y"]]
        mags_db = [20.0 * math.log10(v) for v in mags]

        plt.figure(figsize=(8, 5))
        plt.semilogx(data["x"], mags_db)
        plt.xlabel("Frequency (Hz)")
        plt.ylabel("Magnitude (dB)")
        plt.title("AC Response |V(out)|")
        plt.grid(True, which="both")
        plt.tight_layout()
        plt.savefig(out_path, dpi=160)
        plt.close()

    def _plot_tran(self, tran_in_data, tran_out_data, out_path):
        if not tran_out_data or not tran_out_data["x"] or not tran_out_data["y"]:
            return

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
