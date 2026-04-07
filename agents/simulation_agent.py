# I13/agents/simulation_agent.py

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory
import math
import os
import re
import shutil
import subprocess
import tempfile
from html import escape
from datetime import datetime
from core.analog_defaults import ANALOG_DEFAULTS

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory


class SimulationAgent(BaseAgent):
    AC_EXPECTED_TOPOLOGIES = {
        "rc_lowpass",
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

        if topology == "rc_lowpass" and sizing:

        if not self.ngspice_path:
            memory.write("status", DesignStatus.SIMULATION_FAILED)
            memory.write("simulation_error", "ngspice not found")
            return None

        run_id = self._build_run_id(memory, topology)
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

            memory.write("simulation_results", results)
            memory.write("status", DesignStatus.SIMULATION_COMPLETE)

            log_path = os.path.join(tmpdir, "ngspice.log")
            if os.path.exists(log_path):
                shutil.copy2(log_path, os.path.join(base_dir, "ngspice.log"))

        memory.write("status", DesignStatus.SIMULATION_FAILED)
        return None