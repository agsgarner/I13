# I13/agents/sizing_agent.py

from dataclasses import dataclass, field
import math

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory


@dataclass
class SizingReport:
    success: bool
    notes: list = field(default_factory=list)


class SizingAgent(BaseAgent):
    def run_agent(self, memory: SharedMemory):
        state = memory.get_full_state()
        constraints = state.get("constraints", {})
        topology = state.get("selected_topology")

        if not topology:
            memory.write("status", "sizing_failed")
            memory.write("sizing_report", SizingReport(False, ["No topology selected"]).__dict__)
            return state

        if topology == "rc_lowpass":
            state, report = self._size_rc_lowpass(state, constraints)

        elif topology == "common_source_res_load":
            state, report = self._size_common_source_res_load(state, constraints)

        elif topology == "diff_pair":
            state, report = self._size_diff_pair(state, constraints)

        elif topology == "current_mirror":
            state, report = self._size_current_mirror(state, constraints)

        else:
            report = SizingReport(False, [f"Sizing not implemented for {topology}"])
            memory.write("status", "sizing_failed")
            memory.write("sizing_report", report.__dict__)
            return state

        memory.write("sizing", state["sizing"])
        memory.write("sizing_report", report.__dict__)
        memory.write("status", "sizing_complete")
        return state

    def _size_rc_lowpass(self, state, constraints):
        fc = float(constraints.get("target_fc_hz", 1e3))
        C = float(constraints.get("fixed_cap_f", 10e-9))
        R = 1.0 / (2.0 * math.pi * fc * C)

        state["sizing"] = {
            "R_ohm": R,
            "C_f": C
        }
        return state, SizingReport(True, ["RC low-pass sized from target cutoff"])

    def _size_common_source_res_load(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        gain_db = float(constraints.get("target_gain_db", 20))
        power_limit_mw = float(constraints.get("power_limit_mw", 2.0))

        gain_linear = 10 ** (gain_db / 20.0)

        # very rough initial guess
        I_bias = max(1e-6, (power_limit_mw / 1000.0) / vdd)
        RD = 5000.0
        Vov = 0.2
        muCox = 1e-3

        gm_target = gain_linear / RD
        W_over_L = max(0.5, (2.0 * I_bias) / (muCox * Vov**2))
        L_m = 180e-9
        W_m = W_over_L * L_m

        state["sizing"] = {
            "W_m": W_m,
            "L_m": L_m,
            "R_D": RD,
            "I_bias": I_bias,
            "gm_target": gm_target
        }
        return state, SizingReport(True, ["Common-source resistive-load initial sizing complete"])

    def _size_diff_pair(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        power_limit_mw = float(constraints.get("power_limit_mw", 2.0))

        I_tail = max(1e-6, (power_limit_mw / 1000.0) / vdd)
        Vov = 0.2
        muCox = 1e-3
        L_in = 180e-9
        L_tail = 180e-9

        W_over_L_in = max(0.5, 2.0 * (I_tail / 2.0) / (muCox * Vov**2))
        W_over_L_tail = max(0.5, 2.0 * I_tail / (muCox * Vov**2))

        state["sizing"] = {
            "W_in": W_over_L_in * L_in,
            "L_in": L_in,
            "W_tail": W_over_L_tail * L_tail,
            "L_tail": L_tail,
            "I_tail": I_tail,
            "R_load": 5000.0
        }
        return state, SizingReport(True, ["Diff-pair initial sizing complete"])

    def _size_current_mirror(self, state, constraints):
        I_out = float(constraints.get("target_iout_a", 100e-6))
        Vov = 0.2
        muCox = 1e-3
        L_ref = 180e-9
        L_out = 180e-9

        W_over_L = max(0.5, 2.0 * I_out / (muCox * Vov**2))

        state["sizing"] = {
            "W_ref": W_over_L * L_ref,
            "L_ref": L_ref,
            "W_out": W_over_L * L_out,
            "L_out": L_out,
            "I_ref": I_out
        }
        return state, SizingReport(True, ["Current mirror initial sizing complete"])
    