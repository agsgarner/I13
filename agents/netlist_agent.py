# I13/agents/netlist_agent.py

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory


class NetlistAgent(BaseAgent):
    TEMPLATE_TOPOLOGIES = {
        "rc_lowpass",
        "common_source_res_load",
        "current_mirror",
        "diff_pair",
        "two_stage_miller",
    }

    def run_agent(self, memory: SharedMemory):
        topology = memory.read("selected_topology")
        sizing = memory.read("sizing") or {}
        constraints = memory.read("constraints") or {}

        if not topology or not sizing:
            memory.write("status", "netlist_failed")
            memory.write("netlist_error", "Missing topology or sizing")
            return None

        if topology in self.TEMPLATE_TOPOLOGIES:
            netlist = self._build_template_netlist(topology, sizing, constraints)
            source = "template"
        else:
            netlist = self._build_llm_netlist(topology, sizing, constraints)
            source = "llm"

        if not netlist or ".end" not in netlist.lower():
            memory.write("status", "netlist_failed")
            memory.write("netlist_error", "Generated netlist appears invalid")
            memory.write("netlist_raw", netlist)
            return None

        memory.write("netlist", netlist)
        memory.write("netlist_source", source)
        memory.write("status", "netlist_generated")
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
            vin_dc = float(constraints.get("vin_dc", 0.75))
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
                print i(VOUT)
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

            return f"""* Two-stage Miller op-amp first-pass behavioral placeholder
                VDD vdd 0 DC {vdd}
                VIN in 0 AC 1m DC 0
                E1 n1 0 in 0 1e3
                R1 n1 0 100k
                C1 n1 0 1p
                E2 out 0 n1 0 1e2
                R2 out 0 50k
                CCOMP n1 out {cc}

                .control
                set wr_singlescale
                ac dec 100 1 1e9
                wrdata ac_out.csv frequency vm(out)
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
