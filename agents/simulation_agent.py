import os
import math
import subprocess
import tempfile
from typing import Optional

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory
from core.netlist_generator import generate_rc_lowpass_netlist

# Optional Windows default: used only when NGSPICE_CMD is unset and this file exists.
_DEFAULT_NGSPICE_WINDOWS = (
    r"C:\Users\mearo\OneDrive\Desktop\ngspice\Spice64\bin\ngspice_con.exe"
)


def _ngspice_executable() -> Optional[str]:
    """
    Resolution order:
    1. NGSPICE_CMD env var if set: non-empty string = use it; empty = skip ngspice (opt-out).
    2. If unset: on Windows, use _DEFAULT_NGSPICE_WINDOWS only if that file exists.
    3. Otherwise skip ngspice (analytic-only).
    """
    if "NGSPICE_CMD" in os.environ:
        cmd = os.environ["NGSPICE_CMD"].strip()
        return cmd if cmd else None
    if os.name == "nt" and os.path.isfile(_DEFAULT_NGSPICE_WINDOWS):
        return _DEFAULT_NGSPICE_WINDOWS
    return None


class SimulationAgent(BaseAgent):

    def run(self, memory: SharedMemory):

        topology = memory.read("selected_topology")
        sizing = memory.read("sizing")
        constraints = memory.read("constraints") or {}

        if topology == "rc_lowpass":

            if not sizing:
                memory.write("status", "simulation_failed")
                memory.write(
                    "simulation_results",
                    {"error": "Missing sizing information for rc_lowpass"},
                )
                return None

            R = sizing.get("R_ohm")
            C = sizing.get("C_f")

            if R is None or C is None:
                memory.write("status", "simulation_failed")
                memory.write(
                    "simulation_results",
                    {"error": "R_ohm and C_f must be present in sizing"},
                )
                return None

            # Analytic estimate (for comparison/debugging)
            fc_analytic = 1.0 / (2.0 * math.pi * R * C)
            fc_hint = constraints.get("target_fc_hz", fc_analytic)

            # Build SPICE netlist
            netlist = generate_rc_lowpass_netlist(R, C, fc_hint_hz=fc_hint)

            # Also persist a copy in the project root for inspection/debugging.
            try:
                with open("last_rc_lowpass.cir", "w", encoding="utf-8") as f_debug:
                    f_debug.write(netlist)
            except OSError:
                # Non-fatal; continue even if we can't write the debug file.
                pass

            spice_exe = _ngspice_executable()
            if spice_exe is None:
                # No NGSPICE_CMD: skip external simulator; pipeline still completes.
                results = {
                    "fc_hz_spice": None,
                    "fc_hz_analytic": fc_analytic,
                    "spice_success": False,
                    "spice_skipped": True,
                    "note": (
                        "ngspice not run (NGSPICE_CMD unset or empty). "
                        "Set NGSPICE_CMD to e.g. ngspice or ngspice_con to verify the netlist."
                    ),
                }
                memory.write("simulation_results", results)
                memory.write("status", "simulation_complete")
                return results

            # Run ngspice on the generated netlist
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    cir_path = os.path.join(tmpdir, "rc_lowpass.cir")
                    log_path = os.path.join(tmpdir, "rc_lowpass.log")

                    with open(cir_path, "w", encoding="utf-8") as f:
                        f.write(netlist)

                    completed = subprocess.run(
                        [spice_exe, "-b", "-o", log_path, cir_path],
                        check=False,
                        capture_output=True,
                        text=True,
                    )

                    if completed.returncode != 0:
                        error_msg = (completed.stderr or "") + "\n" + (completed.stdout or "")
                        memory.write("status", "simulation_failed")
                        memory.write(
                            "simulation_results",
                            {
                                "error": "ngspice failed",
                                "details": error_msg.strip(),
                            },
                        )
                        return None

            except FileNotFoundError:
                memory.write("status", "simulation_failed")
                memory.write(
                    "simulation_results",
                    {
                        "error": "ngspice executable not found",
                        "details": f"Could not run: {spice_exe}",
                    },
                )
                return None

            results = {
                "fc_hz_spice": None,
                "fc_hz_analytic": fc_analytic,
                "spice_success": True,
                "spice_skipped": False,
            }

            memory.write("simulation_results", results)
            memory.write("status", "simulation_complete")

            return results

        memory.write("status", "simulation_failed")
        memory.write(
            "simulation_results",
            {"error": f"Simulation not implemented for topology '{topology}'"},
        )
        return None
