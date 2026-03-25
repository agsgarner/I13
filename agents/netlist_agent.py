# I13/agents/netlist_agent.py

from agents.base_agent import BaseAgent
from core.shared_memory import SharedMemory


class NetlistAgent(BaseAgent):
    TEMPLATE_TOPOLOGIES = {
        "rc_lowpass",
        "common_source_res_load",
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
* Includes both AC and transient analyses for demo plots

Vin in 0 DC 0 AC {vin_ac} PULSE(0 {vin_step} 0 1u 1u 1m 2m)
R1 in out {r}
C1 out 0 {c}

.ac dec 100 1 1e6
.tran 10u 10m

.control
set wr_singlescale
run

* AC response
wrdata ac_out.csv frequency vm(out)

* Transient response
wrdata tran_in.csv time v(in)
wrdata tran_out.csv time v(out)

quit
.endc
.end
"""

        if topology == "common_source_res_load":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(constraints.get("vin_dc", 0.9))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            w = float(sizing["W_m"])
            l = float(sizing["L_m"])
            rd = float(sizing["R_D"])

            return f"""* Common-source resistive-load amplifier
VDD vdd 0 DC {vdd}
VIN in 0 DC {vin_dc} AC {vin_ac}
RD vdd out {rd}
M1 out in 0 0 NMOS W={w} L={l}
.model NMOS NMOS (VTO=0.5 KP=100u)
.op
.ac dec 100 1 1e9
.control
set wr_singlescale
run
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
    