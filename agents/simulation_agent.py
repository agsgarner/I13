# I13/agents/simulation_agent.py

import math
import os
import shutil
import subprocess
import tempfile
from datetime import datetime

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory


class SimulationAgent(BaseAgent):
    def __init__(self, llm=None, ngspice_path=None, max_retries=1, wait=0):
        super().__init__(llm=llm, max_retries=max_retries, wait=wait)
        self.ngspice_path = ngspice_path or os.getenv("NGSPICE_PATH") or self._find_ngspice()

    def run_agent(self, memory: SharedMemory):
        netlist = memory.read("netlist")
        topology = memory.read("selected_topology")
        sizing = memory.read("sizing") or {}
        constraints = memory.read("constraints") or {}

        if not netlist:
            memory.write("status", DesignStatus.SIMULATION_FAILED)
            memory.write("simulation_error", "Missing netlist")
            return None

        if not self.ngspice_path:
            memory.write("status", DesignStatus.SIMULATION_FAILED)
            memory.write("simulation_error", "ngspice not found")
            return None

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.join("artifacts", "simulations", run_id)
        os.makedirs(base_dir, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            netlist_path = os.path.join(tmpdir, "generated.sp")
            with open(netlist_path, "w", encoding="utf-8") as handle:
                handle.write(netlist)

            saved_netlist_path = os.path.join(base_dir, "generated.sp")
            with open(saved_netlist_path, "w", encoding="utf-8") as handle:
                handle.write(netlist)

            result = subprocess.run(
                [self.ngspice_path, "-b", "-o", "ngspice.log", netlist_path],
                cwd=tmpdir,
                capture_output=True,
                text=True,
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
                memory.write("status", DesignStatus.SIMULATION_FAILED)
                return sim

            if topology == "rc_lowpass":
                fc_formula = self._formula_fc_from_sizing(sizing)
                if fc_formula is not None:
                    sim["fc_hz_formula"] = fc_formula
                    sim["fc_hz"] = fc_formula
                else:
                    sim["parser_warning"] = "Could not compute formula-based cutoff."

                sim["fc_hz_from_ac"] = sim.get("fc_hz")

            if topology in (
                "common_source_res_load",
                "source_degenerated_cs",
                "common_source_active_load",
                "diode_connected_stage",
                "cascode_amplifier",
                "common_drain",
                "common_gate",
            ):
                vdd = constraints.get("supply_v")
                ibias = sizing.get("I_bias")
                if vdd is not None and ibias is not None:
                    sim["power_mw"] = 1000.0 * float(vdd) * float(ibias)

            memory.write("simulation_results", sim)
            memory.write("status", DesignStatus.SIMULATION_COMPLETE)
            return sim

    def _find_ngspice(self):
        candidates = [
            shutil.which("ngspice"),
            r"C:\Program Files\ngspice-46_64\Spice64\bin\ngspice.exe",
            r"C:\Spice64\bin\ngspice.exe",
        ]
        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    def _safe_write_text(self, path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _formula_fc_from_sizing(self, sizing):
        try:
            r = float(sizing.get("R_ohm", 0.0))
            c = float(sizing.get("C_f", 0.0))
        except Exception:
            return None

        if r <= 0 or c <= 0:
            return None

        return 1.0 / (2.0 * math.pi * r * c)
