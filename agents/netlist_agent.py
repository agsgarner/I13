# I13/agents/netlist_agent.py

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory


class NetlistAgent(BaseAgent):
    TEMPLATE_TOPOLOGIES = {
        "rc_lowpass",
        "common_source_res_load",
        "current_mirror",
        "diff_pair",
        "two_stage_miller",
        "gm_stage",
        "common_drain",
        "common_gate",
        "source_degenerated_cs",
        "common_source_active_load",
        "diode_connected_stage",
        "cascode_amplifier",
        "nand2_cmos",
        "sram6t_cell",
        "lc_oscillator_cross_coupled",
        "bandgap_reference_core",
    }

    def run_agent(self, memory: SharedMemory):
        topology = memory.read("selected_topology")
        sizing = memory.read("sizing") or {}
        constraints = memory.read("constraints") or {}

        if not topology or not sizing:
            memory.write("status", DesignStatus.NETLIST_FAILED)
            memory.write("netlist_error", "Missing topology or sizing")
            return None

        if topology in self.TEMPLATE_TOPOLOGIES:
            netlist = self._build_template_netlist(topology, sizing, constraints)
            source = "template"
        else:
            netlist = self._build_llm_netlist(topology, sizing, constraints)
            source = "llm"

        if not netlist or ".end" not in netlist.lower():
            memory.write("status", DesignStatus.NETLIST_FAILED)
            memory.write("netlist_error", "Generated netlist appears invalid")
            memory.write("netlist_raw", netlist)
            return None

        memory.write("netlist", netlist)
        memory.write("netlist_source", source)
        memory.write("status", DesignStatus.NETLIST_GENERATED)
        return netlist

    def _build_template_netlist(self, topology, sizing, constraints):
        if topology == "rc_lowpass":
            r = float(sizing["R_ohm"])
            c = float(sizing["C_f"])
            vin_ac = float(constraints.get("vin_ac", 1.0))
            vin_step = float(constraints.get("vin_step", 1.0))

            return f"""* RC low-pass filter demo netlist
                Vin in 0 DC 0 AC {vin_ac} PULSE(0 {vin_step} 0 1u 1u 1m 2m)
                R1 in out {r}
                C1 out 0 {c}

                .control
                set wr_singlescale
                ac dec 100 1 1e6
                wrdata ac_out.csv frequency vm(out)
                tran 10u 10m
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "common_source_res_load":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(sizing.get("Vin_bias", constraints.get("vin_dc", 0.75)))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            load_cap = float(constraints.get("load_cap_f", 1e-12))
            rd = float(sizing["R_D"])
            w = float(sizing["W_m"])
            l = float(sizing["L_m"])

            return f"""* Common-source amplifier with resistive load
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac}
                RD vdd out {rd}
                M1 out in 0 0 NMOS W={w} L={l}
                CLOAD out 0 {load_cap}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                ac dec 100 1 1e9
                wrdata ac_out.csv frequency vm(out)
                print v(out) v(in)
                print @m1[gm] @m1[gds] @m1[id]
                quit
                .endc
                .end
                """

        if topology == "current_mirror":
            vdd = float(constraints.get("supply_v", 1.8))
            iref = float(sizing["I_ref"])
            wref = float(sizing["W_ref"])
            lref = float(sizing["L_ref"])
            wout = float(sizing["W_out"])
            lout = float(sizing["L_out"])
            compliance_v = float(constraints.get("compliance_v", 0.8))

            return f"""* MOS current mirror
                VDD vdd 0 DC {vdd}
                VOUT out 0 DC {compliance_v}
                IREF vdd nref DC {iref}
                MREF nref nref 0 0 NMOS W={wref} L={lref}
                MOUT out nref 0 0 NMOS W={wout} L={lout}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                op
                let iop = -i(VOUT)
                print iop
                dc VOUT 0 {vdd} 0.02
                let iout = -i(VOUT)
                wrdata dc_out.csv v(out) iout
                quit
                .endc
                .end
                """

        if topology == "diff_pair":
            vdd = float(constraints.get("supply_v", 1.8))
            vicm = float(constraints.get("vicm_v", 0.9))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            rload = float(sizing["R_load"])
            win = float(sizing["W_in"])
            lin = float(sizing["L_in"])
            wtail = float(sizing["W_tail"])
            ltail = float(sizing["L_tail"])

            return f"""* MOS differential pair
                VDD vdd 0 DC {vdd}
                VIP inp 0 DC {vicm} AC {vin_ac}
                VIN inn 0 DC {vicm} AC {-vin_ac}
                RL1 vdd outp {rload}
                RL2 vdd outn {rload}
                M1 outp inp tail 0 NMOS W={win} L={lin}
                M2 outn inn tail 0 NMOS W={win} L={lin}
                MTAIL tail vbias 0 0 NMOS W={wtail} L={ltail}
                VBIAS vbias 0 DC 0.8
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                ac dec 100 1 1e9
                wrdata ac_out.csv frequency vm(outp)
                quit
                .endc
                .end
                """

        if topology == "two_stage_miller":
            vdd = float(constraints.get("supply_v", 1.8))
            cc = float(sizing["Cc_f"])
            load_cap = float(constraints.get("load_cap_f", 1e-12))
            vin_ac = float(constraints.get("vin_ac", 1.0))
            vin_step = float(constraints.get("vin_step", 0.05))
            vin_cm = float(constraints.get("vin_cm_dc", 0.0))

            return f"""* Two-stage Miller op-amp first-pass behavioral placeholder
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_cm} AC {vin_ac} PULSE(0 {vin_step} 0 2n 2n 100n 200n)
                E1 n1 0 in 0 316.2
                R1 n1 0 100k
                C1 n1 0 1p
                E2 out 0 n1 0 316.2
                R2 out 0 20k
                CLOAD out 0 {load_cap}
                CCOMP n1 out {cc}

                .control
                set wr_singlescale
                op
                ac dec 100 1 1e9
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "gm_stage":
            gm = float(sizing["gm_target_s"])
            i_bias = float(sizing["I_bias_a"])
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            vin_step = float(constraints.get("vin_step", 0.05))
            vdd = float(constraints.get("supply_v", 1.8))
            ro = max(1e3, 4.0 / max(gm, 1e-9))
            cload = float(constraints.get("load_cap_f", 1e-12))
            vin_dc = float(constraints.get("vin_dc", 0.0))

            return f"""* Behavioral gm-stage proxy
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac} PULSE(0 {vin_step} 0 2n 2n 100n 200n)
                G1 out 0 in 0 {gm}
                ROUT out 0 {ro}
                CLOAD out 0 {cload}
                IBIAS vdd out DC {i_bias}

                .control
                set wr_singlescale
                op
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "common_drain":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(constraints.get("vin_dc", 0.8))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            vin_step = float(constraints.get("vin_step", 0.05))
            w = float(sizing["W_m"])
            l = float(sizing["L_m"])
            rs = float(sizing["R_source"])

            return f"""* Common-drain source follower
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac} PULSE({vin_dc} {vin_dc + vin_step} 0 2n 2n 100n 200n)
                M1 vdd in out 0 NMOS W={w} L={l}
                RS out 0 {rs}
                CLOAD out 0 {float(constraints.get("load_cap_f", 1e-12))}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "common_gate":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(constraints.get("vin_dc", 0.35))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            vin_step = float(constraints.get("vin_step", 0.02))
            w = float(sizing["W_m"])
            l = float(sizing["L_m"])
            rd = float(sizing["R_D"])
            vbias = float(sizing["Vbias"])

            return f"""* Common-gate amplifier
                VDD vdd 0 DC {vdd}
                VBIAS gate 0 DC {vbias}
                VIN in 0 DC {vin_dc} AC {vin_ac} PULSE({vin_dc} {vin_dc + vin_step} 0 2n 2n 100n 200n)
                RD vdd out {rd}
                M1 out gate in 0 NMOS W={w} L={l}
                CLOAD out 0 {float(constraints.get("load_cap_f", 1e-12))}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "source_degenerated_cs":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(constraints.get("vin_dc", 0.85))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            w = float(sizing["W_m"])
            l = float(sizing["L_m"])
            rd = float(sizing["R_D"])
            rs = float(sizing["R_S"])

            return f"""* Source-degenerated common-source amplifier
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac}
                RD vdd out {rd}
                RS src 0 {rs}
                M1 out in src 0 NMOS W={w} L={l}
                CLOAD out 0 {float(constraints.get("load_cap_f", 1e-12))}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                quit
                .endc
                .end
                """

        if topology == "common_source_active_load":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(sizing.get("Vin_bias", constraints.get("vin_dc", 0.75)))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            wn = float(sizing["W_n"])
            ln = float(sizing["L_n"])
            wp = float(sizing["W_p"])
            lp = float(sizing["L_p"])
            ibias = float(sizing["I_bias"])

            return f"""* Common-source amplifier with PMOS current-mirror active load
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac}
                IREF nbias 0 DC {ibias}
                MBIAS nbias nbias vdd vdd PMOS W={wp} L={lp}
                MLOAD out nbias vdd vdd PMOS W={wp} L={lp}
                M1 out in 0 0 NMOS W={wn} L={ln}
                CLOAD out 0 {float(constraints.get("load_cap_f", 1e-12))}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)
                .model PMOS PMOS (LEVEL=1 VTO=-0.5 KP=80u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                print v(out) v(nbias) @m1[gm] @m1[gds] @mload[gds]
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                quit
                .endc
                .end
                """

        if topology == "diode_connected_stage":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(constraints.get("vin_dc", 0.75))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            wn = float(sizing["W_n"])
            ln = float(sizing["L_n"])
            wp = float(sizing["W_p"])
            lp = float(sizing["L_p"])

            return f"""* Common-source stage with diode-connected PMOS load
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac}
                MLOAD out out vdd vdd PMOS W={wp} L={lp}
                M1 out in 0 0 NMOS W={wn} L={ln}
                CLOAD out 0 {float(constraints.get("load_cap_f", 1e-12))}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)
                .model PMOS PMOS (LEVEL=1 VTO=-0.5 KP=80u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                quit
                .endc
                .end
                """

        if topology == "cascode_amplifier":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(constraints.get("vin_dc", 0.7))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            rd = float(sizing["R_D"])

            return f"""* NMOS cascode amplifier with resistive load
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac}
                VCAS vbias 0 DC {float(sizing["Vbias_cas"])}
                RD vdd out {rd}
                M2 out vbias x 0 NMOS W={float(sizing["W_cas"])} L={float(sizing["L_cas"])}
                M1 x in 0 0 NMOS W={float(sizing["W_in"])} L={float(sizing["L_in"])}
                CLOAD out 0 {float(constraints.get("load_cap_f", 1e-12))}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                quit
                .endc
                .end
                """

        if topology == "nand2_cmos":
            vdd = float(constraints.get("supply_v", 1.8))
            wn = float(sizing["W_n"])
            ln = float(sizing["L_n"])
            wp = float(sizing["W_p"])
            lp = float(sizing["L_p"])

            return f"""* CMOS 2-input NAND gate
                VDD vdd 0 DC {vdd}
                VA a 0 PULSE(0 {vdd} 0 100p 100p 5n 10n)
                VB b 0 PULSE(0 {vdd} 2.5n 100p 100p 5n 10n)
                MP1 out a vdd vdd PMOS W={wp} L={lp}
                MP2 out b vdd vdd PMOS W={wp} L={lp}
                MN1 out a nmid 0 NMOS W={wn} L={ln}
                MN2 nmid b 0 0 NMOS W={wn} L={ln}
                CLOAD out 0 {float(sizing["C_load"])}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)
                .model PMOS PMOS (LEVEL=1 VTO=-0.5 KP=80u LAMBDA=0.02)

                .control
                tran 50p 40n
                wrdata tran_in_a.csv time v(a)
                wrdata tran_in_b.csv time v(b)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "sram6t_cell":
            vdd = float(constraints.get("supply_v", 1.8))
            return f"""* 6T SRAM cell write/read demo
                VDD vdd 0 DC {vdd}
                VBL bl 0 PULSE({vdd} {vdd} 0 100p 100p 20n 40n)
                VBLB blb 0 PULSE({vdd} 0 4n 100p 100p 8n 20n)
                VWL wl 0 PULSE(0 {vdd} 5n 100p 100p 6n 20n)
                MP1 q qb vdd vdd PMOS W={float(sizing["W_pullup"])} L={float(sizing["L_pullup"])}
                MP2 qb q vdd vdd PMOS W={float(sizing["W_pullup"])} L={float(sizing["L_pullup"])}
                MN1 q qb 0 0 NMOS W={float(sizing["W_pulldown"])} L={float(sizing["L_pulldown"])}
                MN2 qb q 0 0 NMOS W={float(sizing["W_pulldown"])} L={float(sizing["L_pulldown"])}
                MAX1 q wl bl 0 NMOS W={float(sizing["W_access"])} L={float(sizing["L_access"])}
                MAX2 qb wl blb 0 NMOS W={float(sizing["W_access"])} L={float(sizing["L_access"])}
                CQ q 0 {float(sizing["C_storage"])}
                CQB qb 0 {float(sizing["C_storage"])}
                .ic v(q)=0 v(qb)={vdd}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)
                .model PMOS PMOS (LEVEL=1 VTO=-0.5 KP=80u LAMBDA=0.02)

                .control
                tran 50p 30n
                wrdata tran_out.csv time v(q)
                wrdata tran_qb.csv time v(qb)
                quit
                .endc
                .end
                """

        if topology == "lc_oscillator_cross_coupled":
            vdd = float(constraints.get("supply_v", 1.8))
            return f"""* Cross-coupled LC oscillator
                VDD vdd 0 DC {vdd}
                IBias tail 0 DC {float(sizing["I_tail"])}
                L1 vdd outp {float(sizing["L_tank"])}
                L2 vdd outn {float(sizing["L_tank"])}
                C1 outp 0 {0.5 * float(sizing["C_tank"])}
                C2 outn 0 {0.5 * float(sizing["C_tank"])}
                RLOSSP outp 0 {float(sizing["R_tank_loss"])}
                RLOSSN outn 0 {float(sizing["R_tank_loss"])}
                M1 outp outn tail 0 NMOS W={float(sizing["W_pair"])} L={float(sizing["L_pair"])}
                M2 outn outp tail 0 NMOS W={float(sizing["W_pair"])} L={float(sizing["L_pair"])}
                RSTART outp outn 1e6
                .ic v(outp)=0.01 v(outn)=0
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                tran 20p 100n
                wrdata tran_out.csv time v(outp)
                wrdata tran_diff.csv time v(outp,outn)
                quit
                .endc
                .end
                """

        if topology == "bandgap_reference_core":
            vdd = float(constraints.get("supply_v", 1.8))
            icore = float(sizing["I_core"])
            area_ratio = float(sizing["area_ratio"])
            r1 = float(sizing["R1_ohm"])
            r2 = float(sizing["R2_ohm"])

            return f"""* Bandgap-style reference core using BJT Vbe and dVbe
                VDD vdd 0 DC {vdd}
                I1 vdd n1 DC {icore}
                I2 vdd n2 DC {icore}
                Q1 n1 n1 0 QN AREA=1
                Q2 n2 n2 0 QN AREA={area_ratio}
                BREF ref 0 V = v(n1) + ({r2}/{r1})*(v(n1)-v(n2))
                RLOAD ref 0 1e9
                .model QN NPN (IS=1e-15 BF=100)

                .control
                op
                print v(ref) v(n1) v(n2)
                dc VDD 1.2 2.0 0.01
                wrdata dc_out.csv v(vdd) v(ref)
                tran 1u 200u
                wrdata tran_out.csv time v(ref)
                quit
                .endc
                .end
                """

        return None

    def _build_llm_netlist(self, topology, sizing, constraints):
        if self.llm is None:
            return None

        prompt = f"""
            You are generating an ngspice netlist.

            Topology:
            {topology}

            Sizing:
            {sizing}

            Constraints:
            {constraints}

            Return ONLY a valid ngspice netlist.
            Requirements:
            - valid ngspice syntax
            - include at least one useful analysis
            - include .control / run / quit if useful
            - include wrdata statements when possible
            - include .end
            - do not explain anything outside the netlist
            """
        result = self.llm.generate(prompt)

        if isinstance(result, dict):
            return result.get("raw_text") or result.get("netlist")
        return str(result)
