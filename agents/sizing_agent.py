from dataclasses import dataclass, field
import math

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
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
            memory.write("status", DesignStatus.SIZING_FAILED)
            memory.write("sizing_report", SizingReport(False, ["No topology selected"]).__dict__)
            return state

        if topology == "rc_lowpass":
            state, report = self._size_rc_lowpass(state, constraints)

        elif topology == "common_source_res_load":
            state, report = self._size_common_source_res_load(state, constraints)

        elif topology == "diff_pair":
            state, report = self._size_diff_pair(state, constraints)

        elif topology == "bjt_diff_pair":
            state, report = self._size_bjt_diff_pair(state, constraints)

        elif topology == "current_mirror":
            state, report = self._size_current_mirror(state, constraints)

        elif topology == "two_stage_miller":
            state, report = self._size_two_stage_miller(state, constraints)

        elif topology == "gm_stage":
            state, report = self._size_gm_stage(state, constraints)

        elif topology == "common_drain":
            state, report = self._size_common_drain(state, constraints)

        elif topology == "common_gate":
            state, report = self._size_common_gate(state, constraints)

        elif topology == "source_degenerated_cs":
            state, report = self._size_source_degenerated_cs(state, constraints)

        elif topology == "common_source_active_load":
            state, report = self._size_common_source_active_load(state, constraints)

        elif topology == "diode_connected_stage":
            state, report = self._size_diode_connected_stage(state, constraints)

        elif topology == "cascode_amplifier":
            state, report = self._size_cascode_amplifier(state, constraints)

        elif topology == "nand2_cmos":
            state, report = self._size_nand2_cmos(state, constraints)

        elif topology == "sram6t_cell":
            state, report = self._size_sram6t_cell(state, constraints)

        elif topology == "lc_oscillator_cross_coupled":
            state, report = self._size_lc_oscillator(state, constraints)

        elif topology == "bandgap_reference_core":
            state, report = self._size_bandgap_reference(state, constraints)

        else:
            report = SizingReport(False, [f"Sizing not implemented for {topology}"])
            memory.write("status", DesignStatus.SIZING_FAILED)
            memory.write("sizing_report", report.__dict__)
            return state

        memory.write("sizing", state["sizing"])
        memory.write("sizing_report", report.__dict__)
        memory.write("status", DesignStatus.SIZING_COMPLETE)
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
        gain_db = float(constraints.get("target_gain_db", 20.0))
        target_vov_v = float(constraints.get("target_vov_v", 0.2))
        mu_cox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L_m = float(constraints.get("L_m", 180e-9))

        gain_linear = 10 ** (gain_db / 20.0)

        # Choose a reasonable DC output bias near midrail for headroom
        vout_q = float(constraints.get("target_vout_q_v", 0.5 * vdd))

        # Start with a practical resistor guess, then solve current from headroom
        RD = float(constraints.get("R_D_initial", 5000.0))

        # DC current allowed by chosen output quiescent point
        I_bias = max(1e-6, (vdd - vout_q) / RD)

        # Small-signal gm needed for target gain magnitude |Av| ~= gm * RD
        gm_target = gain_linear / RD

        # Check whether chosen I and target Vov support that gm
        # gm ~= 2*Id / Vov  => required Id = gm*Vov/2
        I_required_for_gain = gm_target * target_vov_v / 2.0

        # Use the larger of the two currents:
        # - current needed for the target gain
        # - current set by chosen quiescent point
        I_bias = max(I_bias, I_required_for_gain)

        # Recompute RD so output stays near chosen quiescent voltage
        RD = max(100.0, (vdd - vout_q) / I_bias)

        # Recompute gm target from final RD
        gm_target = gain_linear / RD

        # From square-law first-pass sizing:
        # Id = 0.5 * muCox * (W/L) * Vov^2
        W_over_L = max(0.5, (2.0 * I_bias) / (mu_cox * target_vov_v**2))
        W_m = W_over_L * L_m

        state["sizing"] = {
            "W_m": W_m,
            "L_m": L_m,
            "R_D": RD,
            "I_bias": I_bias,
            "gm_target": gm_target,
            "Vov_target": target_vov_v,
            "Vout_q_target": vout_q
        }

        return state, SizingReport(
            True,
            [
                "Common-source sizing adjusted for gain and DC headroom.",
                f"Chosen Vout_q ≈ {vout_q:.3f} V.",
                f"Estimated I_bias ≈ {I_bias:.3e} A.",
                f"Estimated R_D ≈ {RD:.3f} ohm.",
            ]
        )

    def _size_diff_pair(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        power_limit_mw = float(constraints.get("power_limit_mw", 2.0))
        Vov = float(constraints.get("target_vov_v", 0.2))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L_in = float(constraints.get("L_in_m", 180e-9))
        L_tail = float(constraints.get("L_tail_m", 180e-9))
        R_load = float(constraints.get("R_load_ohm", 5000.0))

        I_tail = max(1e-6, (power_limit_mw / 1000.0) / vdd)

        W_over_L_in = max(0.5, 2.0 * (I_tail / 2.0) / (muCox * Vov**2))
        W_over_L_tail = max(0.5, 2.0 * I_tail / (muCox * Vov**2))

        state["sizing"] = {
            "W_in": W_over_L_in * L_in,
            "L_in": L_in,
            "W_tail": W_over_L_tail * L_tail,
            "L_tail": L_tail,
            "I_tail": I_tail,
            "R_load": R_load,
            "Vov_target": Vov
        }
        return state, SizingReport(True, ["MOS differential pair initial sizing complete"])

    def _size_bjt_diff_pair(self, state, constraints):
        I_tail = float(constraints.get("tail_current_a", 200e-6))
        beta = float(constraints.get("beta", 100))
        Rc = float(constraints.get("collector_res_ohm", 10000))
        Vt = 0.02585

        Ic_each = I_tail / 2.0
        gm = Ic_each / Vt
        re_small = 1.0 / gm

        state["sizing"] = {
            "I_tail": I_tail,
            "Ic_each": Ic_each,
            "beta": beta,
            "R_C": Rc,
            "gm_each": gm,
            "r_e_small_signal": re_small,
            "r_pi_est": beta / gm
        }
        return state, SizingReport(True, ["BJT differential pair sized from tail current"])

    def _size_current_mirror(self, state, constraints):
        I_out = float(constraints.get("target_iout_a", 100e-6))
        ratio = float(constraints.get("mirror_ratio", 1.0))
        Vov = float(constraints.get("target_vov_v", 0.2))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L_ref = float(constraints.get("L_ref_m", 180e-9))
        L_out = float(constraints.get("L_out_m", 180e-9))

        I_ref = I_out / max(ratio, 1e-9)

        W_over_L_ref = max(0.5, 2.0 * I_ref / (muCox * Vov**2))
        W_over_L_out = max(0.5, 2.0 * I_out / (muCox * Vov**2))

        state["sizing"] = {
            "W_ref": W_over_L_ref * L_ref,
            "L_ref": L_ref,
            "W_out": W_over_L_out * L_out,
            "L_out": L_out,
            "I_ref": I_ref,
            "I_out_target": I_out,
            "mirror_ratio": ratio,
            "Vov_target": Vov,
            "compliance_v_est": Vov
        }
        return state, SizingReport(True, ["Current mirror sized from target current and ratio"])

    def _size_two_stage_miller(self, state, constraints):
        ugbw = float(constraints.get("target_ugbw_hz", 1e6))
        load_cap = float(constraints.get("load_cap_f", 1e-12))
        slew_rate = float(constraints.get("target_slew_v_per_us", 1.0)) * 1e6
        supply_v = float(constraints.get("supply_v", 1.8))

        Cc = max(0.2 * load_cap, 0.5e-12)
        gm1 = 2.0 * math.pi * ugbw * Cc
        I2 = slew_rate * Cc
        I1 = max(I2 / 10.0, 10e-6)

        state["sizing"] = {
            "Cc_f": Cc,
            "gm1_target_s": gm1,
            "I_stage1_a": I1,
            "I_stage2_a": I2,
            "supply_v": supply_v
        }
        return state, SizingReport(True, ["Two-stage Miller op-amp initial sizing from UGBW and slew-rate"])

    def _size_gm_stage(self, state, constraints):
        gm_target = float(constraints.get("target_gm_s", 1e-3))
        Vov = float(constraints.get("target_vov_v", 0.2))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L = float(constraints.get("L_m", 180e-9))

        Id = gm_target * Vov / 2.0
        W_over_L = max(0.5, 2.0 * Id / (muCox * Vov**2))
        W = W_over_L * L

        state["sizing"] = {
            "gm_target_s": gm_target,
            "I_bias_a": Id,
            "W_m": W,
            "L_m": L,
            "Vov_target_v": Vov
        }
        return state, SizingReport(True, ["GM stage sized from gm and Vov"])

    def _size_common_drain(self, state, constraints):
        gm_target = float(constraints.get("target_gm_s", 2e-3))
        Vov = float(constraints.get("target_vov_v", 0.18))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L = float(constraints.get("L_m", 180e-9))
        vdd = float(constraints.get("supply_v", 1.8))
        Id = max(20e-6, gm_target * Vov / 2.0)
        W_over_L = max(0.5, 2.0 * Id / (muCox * Vov**2))
        state["sizing"] = {
            "W_m": W_over_L * L,
            "L_m": L,
            "I_bias": Id,
            "R_source": max(200.0, 0.45 * vdd / Id),
            "Vbias": min(vdd - 0.2, 0.7 + Vov),
            "gm_target": gm_target,
        }
        return state, SizingReport(True, ["Common-drain source follower initial sizing complete"])

    def _size_common_gate(self, state, constraints):
        gm_target = float(constraints.get("target_gm_s", 1.5e-3))
        Vov = float(constraints.get("target_vov_v", 0.2))
        muCox = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L = float(constraints.get("L_m", 180e-9))
        vdd = float(constraints.get("supply_v", 1.8))
        Id = max(20e-6, gm_target * Vov / 2.0)
        W_over_L = max(0.5, 2.0 * Id / (muCox * Vov**2))
        rd = max(1e3, float(constraints.get("R_D_ohm", 0.5 * vdd / Id)))
        state["sizing"] = {
            "W_m": W_over_L * L,
            "L_m": L,
            "I_bias": Id,
            "R_D": rd,
            "Vbias": min(vdd - 0.2, 1.0),
            "gm_target": gm_target,
        }
        return state, SizingReport(True, ["Common-gate initial sizing complete"])

    def _size_source_degenerated_cs(self, state, constraints):
        state, report = self._size_common_source_res_load(state, constraints)
        gm = state["sizing"]["gm_target"]
        gain_db = float(constraints.get("target_gain_db", 12.0))
        gain_lin = max(1.0, 10 ** (gain_db / 20.0))
        rs = max(10.0, (max(gm, 1e-9) / gain_lin - 1.0) / max(gm, 1e-9))
        state["sizing"]["R_S"] = max(10.0, rs)
        report.notes.append("Added source degeneration resistor for gain linearization.")
        return state, report

    def _size_common_source_active_load(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        gain_db = float(constraints.get("target_gain_db", 12.0))
        Vov_n = float(constraints.get("target_vov_v", 0.18))
        Vov_p = float(constraints.get("target_vov_p_v", 0.22))
        # Match the LEVEL=1 model parameters used in the template netlist.
        mu_n = float(constraints.get("mu_cox_active_n_a_per_v2", 200e-6))
        mu_p = float(constraints.get("mu_cox_active_p_a_per_v2", 80e-6))
        L = float(constraints.get("L_active_m", 1.0e-6))
        gain_lin = 10 ** (gain_db / 20.0)
        id_bias = max(10e-6, min(30e-6, gain_lin * Vov_n / 40000.0))
        w_n = max(0.5, 2.0 * id_bias / (mu_n * Vov_n**2)) * L
        w_p = max(0.5, 2.0 * id_bias / (mu_p * Vov_p**2)) * L
        state["sizing"] = {
            "W_n": w_n,
            "L_n": L,
            "W_p": w_p,
            "L_p": L,
            "I_bias": id_bias,
            "Vin_bias": 0.5 + Vov_n,
            "target_vout_q": 0.9,
        }
        return state, SizingReport(True, ["Common-source with PMOS active load sized from current target"])

    def _size_diode_connected_stage(self, state, constraints):
        state, report = self._size_common_source_active_load(state, constraints)
        report.notes = ["Diode-connected MOS amplifier sized from active-load starting point"]
        return state, report

    def _size_cascode_amplifier(self, state, constraints):
        vdd = float(constraints.get("supply_v", 1.8))
        gain_db = float(constraints.get("target_gain_db", 15.0))
        Vov = float(constraints.get("target_vov_v", 0.16))
        mu = float(constraints.get("mu_cox_a_per_v2", 1e-3))
        L = float(constraints.get("L_m", 180e-9))
        gain_lin = 10 ** (gain_db / 20.0)
        id_bias = max(30e-6, gain_lin * Vov / 10000.0)
        w = max(0.5, 2.0 * id_bias / (mu * Vov**2)) * L
        rd = max(1000.0, 0.35 * vdd / id_bias)
        state["sizing"] = {
            "W_in": w,
            "L_in": L,
            "W_cas": 1.2 * w,
            "L_cas": L,
            "R_D": rd,
            "I_bias": id_bias,
            "Vbias_cas": 0.9,
        }
        return state, SizingReport(True, ["Cascode amplifier first-pass sizing complete"])

    def _size_nand2_cmos(self, state, constraints):
        L = float(constraints.get("L_m", 180e-9))
        wn = float(constraints.get("W_n_m", 1.2e-6))
        wp = float(constraints.get("W_p_m", 2.4e-6))
        load_cap = float(constraints.get("load_cap_f", 10e-15))
        state["sizing"] = {
            "W_n": wn,
            "L_n": L,
            "W_p": wp,
            "L_p": L,
            "C_load": load_cap,
        }
        return state, SizingReport(True, ["CMOS NAND2 transistor sizes assigned"])

    def _size_sram6t_cell(self, state, constraints):
        L = float(constraints.get("L_m", 180e-9))
        state["sizing"] = {
            "W_pullup": float(constraints.get("W_pullup_m", 0.8e-6)),
            "L_pullup": L,
            "W_pulldown": float(constraints.get("W_pulldown_m", 1.4e-6)),
            "L_pulldown": L,
            "W_access": float(constraints.get("W_access_m", 1.0e-6)),
            "L_access": L,
            "C_storage": float(constraints.get("storage_cap_f", 2e-15)),
        }
        return state, SizingReport(True, ["6T SRAM cell device sizes assigned"])

    def _size_lc_oscillator(self, state, constraints):
        L_tank = float(constraints.get("L_tank_h", 10e-9))
        target_f = float(constraints.get("target_osc_hz", 1e9))
        C_tank = 1.0 / ((2.0 * math.pi * target_f) ** 2 * L_tank)
        L = float(constraints.get("L_m", 180e-9))
        state["sizing"] = {
            "W_pair": float(constraints.get("W_pair_m", 2e-6)),
            "L_pair": L,
            "L_tank": L_tank,
            "C_tank": C_tank,
            "I_tail": float(constraints.get("tail_current_a", 100e-6)),
            "R_tank_loss": float(constraints.get("r_tank_loss_ohm", 10000.0)),
        }
        return state, SizingReport(True, ["Cross-coupled LC oscillator tank values computed"])

    def _size_bandgap_reference(self, state, constraints):
        area_ratio = float(constraints.get("area_ratio", 8.0))
        target_vref = float(constraints.get("target_vref_v", 1.2))
        vt = 0.02585
        dvbe = vt * math.log(max(area_ratio, 1.0001))
        vbe_nom = float(constraints.get("vbe_nom_v", 0.7))
        ratio = max(2.0, (target_vref - vbe_nom) / max(dvbe, 1e-6))
        r1 = float(constraints.get("R1_ohm", 5000.0))
        r2 = ratio * r1
        state["sizing"] = {
            "I_core": float(constraints.get("i_core_a", 20e-6)),
            "area_ratio": area_ratio,
            "R1_ohm": r1,
            "R2_ohm": r2,
        }
        return state, SizingReport(True, ["Bandgap reference sized from target Vref and area ratio"])
    
