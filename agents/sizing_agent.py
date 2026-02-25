# I13/agents/sizing_agent.py

from dataclasses import dataclass, field
from typing import Dict, Any, Tuple
import math

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory


@dataclass
class SizingReport:
    success: bool
    notes: list = field(default_factory=list)


class SizingAgent(BaseAgent):

    def run(self, memory: SharedMemory):

        state = memory.get_full_state()

        constraints = state.get("constraints", {})
        topology = state.get("selected_topology")

        if not topology:
            memory.write("status", "sizing_failed")
            return state, SizingReport(False, ["No topology selected"])

        if topology == "rc_lowpass":
            state, report = self._size_rc(state, constraints)

        elif topology == "common_source_res_load":
            state, report = self._size_common_source(state, constraints)

        elif topology == "diff_pair":
            state, report = self._size_diff_pair(state, constraints)

        elif topology == "current_mirror":
            state, report = self._size_current_mirror(state, constraints)

        else:
            report = SizingReport(False, [f"Sizing not implemented for {topology}"])
            memory.write("status", "sizing_failed")
            return state, report

        memory.write("sizing", state["sizing"])
        memory.write("status", "sizing_complete")
        memory.write("sizing_report", report.__dict__)

        return state, report

    def _size_rc(self, state, constraints):

        fc = constraints.get("target_fc_hz", 1e3)

        C = 10e-9
        R = 1 / (2 * math.pi * fc * C)

        state["sizing"] = {
            "R_ohm": R,
            "C_f": C
        }

        return state, SizingReport(True, ["RC sized from cutoff"])

    def _size_rc(self, state, constraints):
        fc = constraints.get("target_fc_hz", 1e3)

        C = 10e-9
        R = 1 / (2 * math.pi * fc * C)

        state["sizing"] = {
            "R_ohm": R,
            "C_f": C
        }

        return state, SizingReport(True, ["RC sized from target cutoff"])


    def _size_common_source(self, state, constraints):
        vdd = constraints.get("supply_v", 1.8)
        gain_db = constraints.get("target_gain_db", 20)
        power_limit_mw = constraints.get("power_limit_mw", 2)

        gain_linear = 10 ** (gain_db / 20)

        I_bias = (power_limit_mw / 1000) / vdd

        gm_target = gain_linear / 5000  # assume RD ≈ 5kΩ baseline
        Vov = 0.2
        W_over_L = 2 * I_bias / (1e-3 * Vov**2)

        state["sizing"] = {
            "W_m": W_over_L * 180e-9,
            "L_m": 180e-9,
            "R_D": 5000,
            "I_bias": I_bias
        }

        return state, SizingReport(True, ["Common-source initial sizing complete"])


    def _size_diff_pair(self, state, constraints):
        vdd = constraints.get("supply_v", 1.8)
        power_limit_mw = constraints.get("power_limit_mw", 2)

        I_tail = (power_limit_mw / 1000) / vdd
        Vov = 0.2

        W_over_L = 2 * (I_tail / 2) / (1e-3 * Vov**2)

        state["sizing"] = {
            "W_in": W_over_L * 180e-9,
            "L_in": 180e-9,
            "W_tail": W_over_L * 180e-9,
            "L_tail": 180e-9,
            "I_tail": I_tail,
            "R_load": 5000
        }

        return state, SizingReport(True, ["Diff pair initial sizing complete"])


    def _size_current_mirror(self, state, constraints):
        I_out = constraints.get("target_iout_a", 100e-6)
        Vov = 0.2

        W_over_L = 2 * I_out / (1e-3 * Vov**2)

        state["sizing"] = {
            "W_ref": W_over_L * 180e-9,
            "L_ref": 180e-9,
            "W_out": W_over_L * 180e-9,
            "L_out": 180e-9,
            "I_ref": I_out
        }

        return state, SizingReport(True, ["Current mirror initial sizing complete"])