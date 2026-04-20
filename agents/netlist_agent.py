# I13/agents/netlist_agent.py

import os
import re

from agents.base_agent import BaseAgent
from agents.design_status import DesignStatus
from core.shared_memory import SharedMemory


class NetlistAgent(BaseAgent):
    STAGE_MARKER_PREFIX = "* STAGE"
    ANALYSIS_TOKENS = {
        "op": ["\nop", "\n                op"],
        "ac": ["\n                ac ", "\nac "],
        "dc": ["\n                dc ", "\ndc "],
        "tran": ["\n                tran ", "\ntran "],
    }

    TEMPLATE_TOPOLOGIES = {
        "rc_lowpass",
        "rlc_lowpass_2nd_order",
        "rlc_highpass_2nd_order",
        "rlc_bandpass_2nd_order",
        "common_source_res_load",
        "current_mirror",
        "wilson_current_mirror",
        "cascode_current_mirror",
        "widlar_current_mirror",
        "diff_pair",
        "two_stage_miller",
        "folded_cascode_opamp",
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
        "comparator",
    }

    def run_agent(self, memory: SharedMemory):
        topology = memory.read("selected_topology")
        sizing = memory.read("sizing") or {}
        constraints = memory.read("constraints") or {}
        case_meta = memory.read("case_metadata") or {}

        if not topology or not sizing:
            memory.write("status", DesignStatus.NETLIST_FAILED)
            memory.write("netlist_error", "Missing topology or sizing")
            return None

        if topology == "composite_pipeline":
            netlist, source = self._build_composite_pipeline_netlist(memory, sizing, constraints)
        elif topology in self.TEMPLATE_TOPOLOGIES:
            netlist = self._build_template_netlist(topology, sizing, constraints, case_meta)
            source = "template"
        else:
            netlist = self._build_llm_netlist(topology, sizing, constraints, memory=memory)
            source = "llm"

        if not netlist or ".end" not in netlist.lower():
            memory.write("status", DesignStatus.NETLIST_FAILED)
            memory.write("netlist_error", "Generated netlist appears invalid")
            memory.write("netlist_raw", netlist)
            return None

        plan_error = self._validate_netlist_against_plan(memory, netlist)
        if plan_error:
            memory.write("status", DesignStatus.NETLIST_FAILED)
            memory.write("netlist_error", plan_error)
            memory.write("netlist_raw", netlist)
            return None

        if topology == "composite_pipeline":
            structure = self._validate_composite_netlist_structure(memory, netlist)
            memory.write("netlist_stage_report", structure)
            if not structure.get("valid"):
                memory.write("status", DesignStatus.NETLIST_FAILED)
                memory.write("netlist_error", structure.get("error") or "Composite netlist structure invalid.")
                memory.write("netlist_raw", netlist)
                return None

        memory.write("netlist", netlist)
        memory.write("netlist_source", source)
        memory.write("status", DesignStatus.NETLIST_GENERATED)
        return netlist

    def _validate_netlist_against_plan(self, memory: SharedMemory, netlist: str):
        plan = ((memory.read("case_metadata") or {}).get("simulation_plan") or {})
        analyses = plan.get("analyses") or []
        lower_netlist = netlist.lower()

        missing = []
        for analysis in analyses:
            tokens = self.ANALYSIS_TOKENS.get(analysis, [])
            if tokens and not any(token in lower_netlist for token in tokens):
                missing.append(analysis)

        if missing:
            return (
                "Generated netlist does not include the planned analyses: "
                + ", ".join(missing)
            )
        return None

    def _validate_composite_netlist_structure(self, memory: SharedMemory, netlist: str):
        plan = memory.read("topology_plan") or {}
        planned_stages = plan.get("stages") or []
        parsed_stages = self._extract_stage_markers(netlist)

        if parsed_stages:
            continuity_issues = []
            for idx in range(1, len(parsed_stages)):
                prev_out = parsed_stages[idx - 1].get("output")
                cur_in = parsed_stages[idx].get("input")
                if prev_out and cur_in and prev_out != cur_in:
                    continuity_issues.append(
                        f"Stage {idx} output node '{prev_out}' does not match stage {idx + 1} input node '{cur_in}'."
                    )

            planned_topologies = [item.get("topology") for item in planned_stages if isinstance(item, dict)]
            realized_topologies = [item.get("topology") for item in parsed_stages]
            stage_count_match = len(planned_topologies) == len(realized_topologies)
            topology_order_match = planned_topologies == realized_topologies if planned_topologies else None

            valid = (not continuity_issues) and (stage_count_match or not planned_topologies)
            payload = {
                "valid": valid,
                "mode": "marker_validated",
                "planned_stage_count": len(planned_topologies),
                "realized_stage_count": len(realized_topologies),
                "planned_topologies": planned_topologies,
                "realized_topologies": realized_topologies,
                "stage_count_match": stage_count_match,
                "topology_order_match": topology_order_match,
                "continuity_issues": continuity_issues,
                "stages": parsed_stages,
            }
            if not valid:
                payload["error"] = (
                    "Composite stage marker validation failed. "
                    + "; ".join(continuity_issues or ["Stage count did not match planned stage count."])
                )
            return payload

        lower = netlist.lower()
        has_in = " in " in lower or "\nin " in lower
        has_out = " out " in lower or "\nout " in lower
        has_control = ".control" in lower and ".endc" in lower
        valid = has_in and has_out and has_control
        return {
            "valid": valid,
            "mode": "heuristic",
            "planned_stage_count": len(planned_stages),
            "realized_stage_count": None,
            "stage_count_match": None,
            "topology_order_match": None,
            "stages": [],
            "error": None if valid else "Composite netlist failed heuristic I/O/control validation.",
        }

    def _extract_stage_markers(self, netlist: str):
        stages = []
        marker_re = re.compile(
            r"^\*\s*STAGE\s+idx=(?P<idx>\d+)\s+name=(?P<name>\S+)\s+"
            r"topology=(?P<topology>\S+)\s+input=(?P<input>\S+)\s+output=(?P<output>\S+)",
            re.IGNORECASE,
        )
        for raw in (netlist or "").splitlines():
            line = raw.strip()
            match = marker_re.match(line)
            if not match:
                continue
            stages.append(
                {
                    "idx": int(match.group("idx")),
                    "name": match.group("name"),
                    "topology": match.group("topology"),
                    "input": match.group("input"),
                    "output": match.group("output"),
                }
            )
        stages.sort(key=lambda item: item.get("idx", 0))
        return stages

    def _build_template_netlist(self, topology, sizing, constraints, case_meta=None):
        case_meta = case_meta or {}
        if topology == "rc_lowpass":
            r = float(sizing["R_ohm"])
            c = float(sizing["C_f"])
            vin_ac = float(constraints.get("vin_ac", 1.0))
            vin_step = float(constraints.get("vin_step", 1.0))

            return f"""* RC low-pass filter demo netlist
                Vin in 0 DC 0 AC {vin_ac} PULSE(0 {vin_step} 0 1u 1u 20m 40m)
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

        if topology == "rlc_lowpass_2nd_order":
            r = float(sizing["R_ohm"])
            l_h = float(sizing["L_h"])
            c_f = float(sizing["C_f"])
            vin_ac = float(constraints.get("vin_ac", 1.0))
            vin_step = float(constraints.get("vin_step", 1.0))
            source_res = float(sizing.get("source_res_ohm", constraints.get("source_res_ohm", 50.0)))
            load_res = float(sizing.get("load_res_ohm", constraints.get("load_res_ohm", 10000.0)))
            f_stop = max(1e6, 100.0 * float(constraints.get("target_fc_hz", 5e3)))

            return f"""* Second-order RLC low-pass filter
                Vin in 0 DC 0 AC {vin_ac} PULSE(0 {vin_step} 0 1u 1u 20m 40m)
                RSRC in nsrc {source_res}
                R1 nsrc n1 {r}
                L1 n1 out {l_h}
                C1 out 0 {c_f}
                RLOAD out 0 {load_res}

                .control
                set wr_singlescale
                ac dec 200 1 {f_stop}
                wrdata ac_out.csv frequency vm(out)
                tran 2u 2m
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "rlc_highpass_2nd_order":
            r = float(sizing["R_ohm"])
            l_h = float(sizing["L_h"])
            c_f = float(sizing["C_f"])
            vin_ac = float(constraints.get("vin_ac", 1.0))
            vin_step = float(constraints.get("vin_step", 1.0))
            source_res = float(sizing.get("source_res_ohm", constraints.get("source_res_ohm", 50.0)))
            load_res = float(sizing.get("load_res_ohm", constraints.get("load_res_ohm", 5000.0)))
            f_stop = max(1e6, 100.0 * float(constraints.get("target_fc_hz", 2e3)))

            return f"""* Second-order RLC high-pass filter
                Vin in 0 DC 0 AC {vin_ac} PULSE(0 {vin_step} 0 1u 1u 20m 40m)
                RSRC in nsrc {source_res}
                C1 nsrc n1 {c_f}
                L1 n1 0 {l_h}
                R1 n1 out {r}
                RLOAD out 0 {load_res}

                .control
                set wr_singlescale
                ac dec 200 1 {f_stop}
                wrdata ac_out.csv frequency vm(out)
                tran 2u 2m
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "rlc_bandpass_2nd_order":
            r = float(sizing["R_ohm"])
            l_h = float(sizing["L_h"])
            c_f = float(sizing["C_f"])
            vin_ac = float(constraints.get("vin_ac", 1.0))
            vin_step = float(constraints.get("vin_step", 0.5))
            source_res = float(sizing.get("source_res_ohm", constraints.get("source_res_ohm", 50.0)))
            center_hz = float(constraints.get("target_center_hz", 20e3))
            f_stop = max(1e6, 100.0 * center_hz)

            return f"""* Second-order RLC band-pass filter
                Vin in 0 DC 0 AC {vin_ac} PULSE(0 {vin_step} 0 1u 1u 20m 40m)
                RSRC in nsrc {source_res}
                L1 nsrc n1 {l_h}
                C1 n1 n2 {c_f}
                R1 n2 0 {r}

                .control
                set wr_singlescale
                ac dec 200 10 {f_stop}
                wrdata ac_out.csv frequency vm(n2)
                tran 1u 1m
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(n2)
                quit
                .endc
                .end
                """

        if topology == "common_source_res_load":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(sizing.get("Vin_bias", constraints.get("vin_dc", 0.75)))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            vin_step = float(constraints.get("vin_step", 0.05))
            load_cap = float(constraints.get("load_cap_f", 1e-12))
            rd = float(sizing["R_D"])
            w = float(sizing["W_m"])
            l = float(sizing["L_m"])

            return f"""* Common-source amplifier with resistive load
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac} PULSE({vin_dc} {vin_dc + vin_step} 0 2n 2n 100n 200n)
                RD vdd out {rd}
                M1 out in 0 0 NMOS W={w} L={l}
                CLOAD out 0 {load_cap}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                print i(VDD) v(out) v(in)
                ac dec 100 1 1e9
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
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
                print @mref[id] @mref[gm] @mref[gds] @mref[vgs] @mref[vds]
                print @mout[id] @mout[gm] @mout[gds] @mout[vgs] @mout[vds]
                dc VOUT 0 {vdd} 0.02
                let iout = -i(VOUT)
                wrdata dc_out.csv v(out) iout
                quit
                .endc
                .end
                """

        if topology == "wilson_current_mirror":
            vdd = float(constraints.get("supply_v", 1.8))
            iref = float(sizing["I_ref"])
            wref = float(sizing["W_ref"])
            lref = float(sizing["L_ref"])
            wout = float(sizing["W_out"])
            lout = float(sizing["L_out"])
            waux = float(sizing["W_aux"])
            laux = float(sizing["L_aux"])
            compliance_v = float(constraints.get("compliance_v", 0.8))

            return f"""* Wilson current mirror
                VDD vdd 0 DC {vdd}
                VOUT out 0 DC {compliance_v}
                IREF vdd nref DC {iref}
                M1 nref nref 0 0 NMOS W={wref} L={lref}
                M2 out nref 0 0 NMOS W={wout} L={lout}
                M3 nref out 0 0 NMOS W={waux} L={laux}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                op
                let iop = -i(VOUT)
                print iop
                print @m1[id] @m1[gm] @m1[gds] @m1[vgs] @m1[vds]
                print @m2[id] @m2[gm] @m2[gds] @m2[vgs] @m2[vds]
                print @m3[id] @m3[gm] @m3[gds] @m3[vgs] @m3[vds]
                dc VOUT 0 {vdd} 0.02
                let iout = -i(VOUT)
                wrdata dc_out.csv v(out) iout
                quit
                .endc
                .end
                """

        if topology == "cascode_current_mirror":
            vdd = float(constraints.get("supply_v", 1.8))
            iref = float(sizing["I_ref"])
            compliance_v = float(constraints.get("compliance_v", 0.9))

            return f"""* Cascode current mirror
                VDD vdd 0 DC {vdd}
                VCAS vcas 0 DC {float(sizing["Vbias_cas"])}
                VOUT out 0 DC {compliance_v}
                IREF vdd nref DC {iref}
                MREFC nref vcas nx 0 NMOS W={float(sizing["W_cas"])} L={float(sizing["L_cas"])}
                MREF nx nref 0 0 NMOS W={float(sizing["W_ref"])} L={float(sizing["L_ref"])}
                MOUTC out vcas ny 0 NMOS W={float(sizing["W_cas"])} L={float(sizing["L_cas"])}
                MOUT ny nref 0 0 NMOS W={float(sizing["W_out"])} L={float(sizing["L_out"])}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                op
                let iop = -i(VOUT)
                print iop
                print @mref[id] @mref[gm] @mref[gds] @mref[vgs] @mref[vds]
                print @mrefc[id] @mrefc[gm] @mrefc[gds] @mrefc[vgs] @mrefc[vds]
                print @mout[id] @mout[gm] @mout[gds] @mout[vgs] @mout[vds]
                print @moutc[id] @moutc[gm] @moutc[gds] @moutc[vgs] @moutc[vds]
                dc VOUT 0 {vdd} 0.02
                let iout = -i(VOUT)
                wrdata dc_out.csv v(out) iout
                quit
                .endc
                .end
                """

        if topology == "widlar_current_mirror":
            vdd = float(constraints.get("supply_v", 1.8))
            iref = float(sizing["I_ref"])
            compliance_v = float(constraints.get("compliance_v", 0.8))

            return f"""* Widlar-style current mirror with source degeneration
                VDD vdd 0 DC {vdd}
                VOUT out 0 DC {compliance_v}
                IREF vdd nref DC {iref}
                MREF nref nref 0 0 NMOS W={float(sizing["W_ref"])} L={float(sizing["L_ref"])}
                RDEG nsrc 0 {float(sizing["R_emitter_deg_ohm"])}
                MOUT out nref nsrc 0 NMOS W={float(sizing["W_out"])} L={float(sizing["L_out"])}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                op
                let iop = -i(VOUT)
                print iop
                print @mref[id] @mref[gm] @mref[gds] @mref[vgs] @mref[vds]
                print @mout[id] @mout[gm] @mout[gds] @mout[vgs] @mout[vds]
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
            vin_step = float(constraints.get("vin_step", 0.02))
            rload = float(sizing["R_load"])
            cload = float(constraints.get("load_cap_f", 0.5e-12))
            win = float(sizing["W_in"])
            lin = float(sizing["L_in"])
            wtail = float(sizing["W_tail"])
            ltail = float(sizing["L_tail"])

            return f"""* MOS differential pair
                VDD vdd 0 DC {vdd}
                VIP inp 0 DC {vicm} AC {vin_ac} PULSE({vicm} {vicm + vin_step} 0 2n 2n 100n 200n)
                VIN inn 0 DC {vicm} AC {-vin_ac} PULSE({vicm} {vicm - vin_step} 0 2n 2n 100n 200n)
                RL1 vdd outp {rload}
                RL2 vdd outn {rload}
                CLOADP outp 0 {cload}
                CLOADN outn 0 {cload}
                M1 outp inp tail 0 NMOS W={win} L={lin}
                M2 outn inn tail 0 NMOS W={win} L={lin}
                MTAIL tail vbias 0 0 NMOS W={wtail} L={ltail}
                VBIAS vbias 0 DC 0.8
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                print i(VDD) v(outp) v(outn)
                print @m1[gm] @m1[gds] @m1[id] @m1[vgs] @m1[vds]
                print @m2[gm] @m2[gds] @m2[id] @m2[vgs] @m2[vds]
                print @mtail[gm] @mtail[gds] @mtail[id] @mtail[vgs] @mtail[vds]
                ac dec 100 1 1e9
                wrdata ac_out.csv frequency vm(outp,outn)
                tran 1n 1u
                wrdata tran_in.csv time v(inp)
                wrdata tran_out.csv time v(outp)
                wrdata tran_outn.csv time v(outn)
                wrdata tran_diff.csv time v(outp,outn)
                quit
                .endc
                .end
                """

        if topology == "two_stage_miller":
            if case_meta.get("demo_model") in {"behavioral_opamp_proxy", "native_telescopic"}:
                return self._build_telescopic_ota_netlist(sizing, constraints)
            return self._build_two_stage_miller_transistor_netlist(sizing, constraints)

        if topology == "gm_stage":
            return self._build_gm_stage_transistor_netlist(sizing, constraints)

        if topology == "folded_cascode_opamp":
            return self._build_folded_cascode_transistor_netlist(sizing, constraints)

        if topology == "common_drain":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(sizing.get("Vin_bias", constraints.get("vin_dc", 0.8)))
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
                print i(VDD) v(out)
                print @m1[gm] @m1[gds] @m1[id] @m1[vgs] @m1[vds]
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
                print i(VDD) v(out)
                print @m1[gm] @m1[gds] @m1[id] @m1[vgs] @m1[vds]
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
            vin_step = float(constraints.get("vin_step", 0.05))
            w = float(sizing["W_m"])
            l = float(sizing["L_m"])
            rd = float(sizing["R_D"])
            rs = float(sizing["R_S"])

            return f"""* Source-degenerated common-source amplifier
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac} PULSE({vin_dc} {vin_dc + vin_step} 0 2n 2n 100n 200n)
                RD vdd out {rd}
                RS src 0 {rs}
                M1 out in src 0 NMOS W={w} L={l}
                CLOAD out 0 {float(constraints.get("load_cap_f", 1e-12))}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                print i(VDD) v(out)
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "common_source_active_load":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(sizing.get("Vin_bias", constraints.get("vin_dc", 0.75)))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            vin_step = float(constraints.get("vin_step", 0.03))
            wn = float(sizing["W_n"])
            ln = float(sizing["L_n"])
            wp = float(sizing["W_p"])
            lp = float(sizing["L_p"])
            ibias = float(sizing["I_bias"])

            return f"""* Common-source amplifier with PMOS current-mirror active load
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac} PULSE({vin_dc} {vin_dc + vin_step} 0 2n 2n 100n 200n)
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
                print i(VDD) v(out) v(nbias) @m1[gm] @m1[gds] @m1[id] @m1[vgs] @m1[vds] @mload[gds] @mload[id]
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "diode_connected_stage":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(constraints.get("vin_dc", 0.75))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            vin_step = float(constraints.get("vin_step", 0.03))
            wn = float(sizing["W_n"])
            ln = float(sizing["L_n"])
            wp = float(sizing["W_p"])
            lp = float(sizing["L_p"])

            return f"""* Common-source stage with diode-connected PMOS load
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac} PULSE({vin_dc} {vin_dc + vin_step} 0 2n 2n 100n 200n)
                MLOAD out out vdd vdd PMOS W={wp} L={lp}
                M1 out in 0 0 NMOS W={wn} L={ln}
                CLOAD out 0 {float(constraints.get("load_cap_f", 1e-12))}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)
                .model PMOS PMOS (LEVEL=1 VTO=-0.5 KP=80u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                print i(VDD) v(out)
                print @m1[gm] @m1[gds] @m1[id] @m1[vgs] @m1[vds]
                print @mload[gm] @mload[gds] @mload[id] @mload[vsg] @mload[vsd]
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

        if topology == "cascode_amplifier":
            vdd = float(constraints.get("supply_v", 1.8))
            vin_dc = float(constraints.get("vin_dc", 0.7))
            vin_ac = float(constraints.get("vin_ac", 1e-3))
            vin_step = float(constraints.get("vin_step", 0.02))
            rd = float(sizing["R_D"])

            return f"""* NMOS cascode amplifier with resistive load
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac} PULSE({vin_dc} {vin_dc + vin_step} 0 2n 2n 100n 200n)
                VCAS vbias 0 DC {float(sizing["Vbias_cas"])}
                RD vdd out {rd}
                M2 out vbias x 0 NMOS W={float(sizing["W_cas"])} L={float(sizing["L_cas"])}
                M1 x in 0 0 NMOS W={float(sizing["W_in"])} L={float(sizing["L_in"])}
                CLOAD out 0 {float(constraints.get("load_cap_f", 1e-12))}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                print i(VDD) v(out)
                print @m1[gm] @m1[gds] @m1[id] @m1[vgs] @m1[vds]
                print @m2[gm] @m2[gds] @m2[id] @m2[vgs] @m2[vds]
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
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
                VBLB blb 0 PULSE({vdd} 0 4n 100p 100p 12n 30n)
                VWL wl 0 PULSE(0 {vdd} 5n 100p 100p 10n 30n)
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
                wrdata tran_bl.csv time v(bl)
                wrdata tran_blb.csv time v(blb)
                wrdata tran_wl.csv time v(wl)
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
                .ic v(outp)={vdd + 0.01} v(outn)={vdd - 0.01}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                tran 20p 100n uic
                wrdata tran_out.csv time v(outp)
                wrdata tran_outn.csv time v(outn)
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

        if topology == "comparator":
            return self._build_dynamic_comparator_transistor_netlist(sizing, constraints)

        return None

    def _build_telescopic_ota_netlist(self, sizing: dict, constraints: dict):
        vdd = float(constraints.get("supply_v", 1.8))
        vicm = float(sizing.get("Vicm_v", constraints.get("vin_cm_dc", 0.9)))
        vin_ac = float(constraints.get("vin_ac", 1e-3))
        vin_step = float(constraints.get("vin_step", 0.03))
        cload = float(constraints.get("load_cap_f", 1e-12))

        return f"""* Telescopic cascode OTA transistor-level first-pass netlist
                VDD vdd 0 DC {vdd}
                VINP inp 0 DC {vicm} AC {vin_ac} PULSE({vicm} {vicm + vin_step} 0 2n 2n 100n 200n)
                VBN vbn 0 DC {float(sizing['Vbias_n'])}
                VBP vbp 0 DC {float(sizing['Vbias_p'])}
                IREF nbias 0 DC {float(sizing['I_tail'])}
                MPBIAS nbias vbp vdd vdd PMOS W={float(sizing['W_load_p'])} L={float(sizing['L_load_p'])}
                MPLOAD out vbp vdd vdd PMOS W={float(sizing['W_load_p'])} L={float(sizing['L_load_p'])}
                MNCAS out vbn x 0 NMOS W={float(sizing['W_cas_n'])} L={float(sizing['L_cas_n'])}
                MNIN x inp 0 0 NMOS W={float(sizing['W_in'])} L={float(sizing['L_in'])}
                CLOAD out 0 {cload}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)
                .model PMOS PMOS (LEVEL=1 VTO=-0.5 KP=80u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                print i(VDD) v(out) v(x)
                ac dec 100 1 1e9
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(inp)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

    def _build_two_stage_miller_transistor_netlist(self, sizing: dict, constraints: dict):
        vdd = float(constraints.get("supply_v", 1.8))
        cc = float(sizing["Cc_f"])
        load_cap = float(constraints.get("load_cap_f", 1e-12))
        vin_ac = float(constraints.get("vin_ac", 1.0))
        vin_step = float(constraints.get("vin_step", 0.05))
        vin_cm = float(constraints.get("vin_cm_dc", 0.5 * vdd))
        vref = 0.5 * vdd
        stage_gain = float(sizing.get("stage_gain_linear", 316.2))

        return f"""* Two-stage Miller op-amp high-fidelity macro-model
                VDD vdd 0 DC {vdd}
                VCM vcm 0 DC {vin_cm}
                VREF ref 0 DC {vref}
                VIN in 0 DC {vin_cm} AC {vin_ac} PULSE({vin_cm} {vin_cm + vin_step} 0 2n 2n 100n 200n)
                E1 n1 0 in vcm {stage_gain}
                R1 n1 0 100k
                C1 n1 0 1p
                E2 raw ref n1 0 {stage_gain}
                R2 raw ref 20k
                CLOAD raw 0 {load_cap}
                CCOMP n1 raw {cc}
                BOUT out 0 V = 0.5*v(vdd)*(1 + tanh((v(raw)-v(ref))/0.2))
                RMON out 0 1e9

                .control
                set wr_singlescale
                op
                print i(VDD) v(out)
                ac dec 100 1 1e9
                wrdata ac_out.csv frequency vm(raw)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

    def _build_gm_stage_transistor_netlist(self, sizing: dict, constraints: dict):
        gm_target = float(sizing["gm_target_s"])
        i_bias = float(sizing["I_bias_a"])
        vin_ac = float(constraints.get("vin_ac", 1e-3))
        vin_step = float(constraints.get("vin_step", 0.05))
        vdd = float(constraints.get("supply_v", 1.8))
        cload = float(constraints.get("load_cap_f", 1e-12))
        vin_dc = float(constraints.get("vin_dc", 0.75))
        vov = float(sizing.get("Vov_target_v", constraints.get("target_vov_v", 0.18)))
        l = float(sizing.get("L_m", constraints.get("L_m", 180e-9)))
        w = float(sizing.get("W_m", 2.0 * max(i_bias, 1e-9) * l / max(float(constraints.get("mu_cox_a_per_v2", 200e-6)) * max(vov, 1e-6) ** 2, 1e-30)))
        rload = max(500.0, 1.0 / max(gm_target * 0.35, 1e-9))

        return f"""* Transistor-level gm stage
                VDD vdd 0 DC {vdd}
                VIN in 0 DC {vin_dc} AC {vin_ac} PULSE({vin_dc} {vin_dc + vin_step} 0 2n 2n 100n 200n)
                IBIAS src 0 DC {i_bias}
                M1 out in src 0 NMOS W={w} L={l}
                RD vdd out {rload}
                CLOAD out 0 {cload}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                set wr_singlescale
                op
                print i(VDD) v(out)
                print @m1[gm] @m1[gds] @m1[id] @m1[vgs] @m1[vds]
                ac dec 100 1 1e8
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(in)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

    def _build_folded_cascode_transistor_netlist(self, sizing: dict, constraints: dict):
        vdd = float(constraints.get("supply_v", 1.8))
        vin_cm = float(sizing.get("Vcm_ref", constraints.get("vin_cm_dc", 0.9)))
        vin_ac = float(constraints.get("vin_ac", 1e-3))
        vin_step = float(constraints.get("vin_step", 0.02))
        cload = float(constraints.get("load_cap_f", 1e-12))
        dc_gain = float(sizing["dc_gain_linear"])
        gm1_target = float(
            sizing.get(
                "gm1_target_s",
                2.0 * 3.141592653589793 * float(constraints.get("target_ugbw_hz", 15e6)) * cload,
            )
        )
        target_ugbw = gm1_target / max(2.0 * 3.141592653589793 * cload, 1e-30)
        fp_hz = max(target_ugbw / max(dc_gain, 1.0), 1.0)
        rpole = 1e3
        cpole = 1.0 / (2.0 * 3.141592653589793 * rpole * fp_hz)

        return f"""* Folded-cascode OTA high-fidelity macro-model
                VDD vdd 0 DC {vdd}
                VCM vcm 0 DC {vin_cm}
                VINP inp 0 DC {vin_cm} AC {vin_ac} PULSE({vin_cm - 0.5 * vin_step} {vin_cm + 0.5 * vin_step} 0 2n 2n 100n 200n)
                VINN inn 0 DC {vin_cm} AC {-vin_ac}
                EDIFF nraw 0 inp inn {dc_gain}
                RPOLE nraw out {rpole}
                CPOLE out 0 {cpole}
                CLOAD out 0 {cload}
                IBIAS vdd 0 DC {float(sizing["I_tail"])}

                .control
                set wr_singlescale
                op
                print i(VDD) v(out) v(nraw)
                ac dec 120 1 1e9
                wrdata ac_out.csv frequency vm(out)
                tran 1n 1u
                wrdata tran_in.csv time v(inp)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

    def _build_dynamic_comparator_transistor_netlist(self, sizing: dict, constraints: dict):
        vdd = float(constraints.get("supply_v", 1.8))
        vcm = float(sizing["vcm_v"])
        overdrive = float(sizing["input_overdrive_v"])
        cload = float(sizing["load_cap_f"])
        tail_current = float(sizing["tail_current_a"])
        l = float(constraints.get("L_m", 180e-9))
        mu_n = float(constraints.get("mu_cox_a_per_v2", 200e-6))
        vov = max(0.08, min(0.25, float(constraints.get("target_vov_v", 0.16))))
        id_each = max(0.5 * tail_current, 1e-9)
        w_in = max(0.5, 2.0 * id_each / max(mu_n * vov**2, 1e-30)) * l
        r_load = max(1500.0, 0.65 * vdd / max(tail_current, 1e-9))

        return f"""* Differential comparator front-end (transistor-level)
                VDD vdd 0 DC {vdd}
                VIP inp 0 PULSE({vcm - 0.5 * overdrive} {vcm + 0.5 * overdrive} 2n 100p 100p 20n 40n)
                VIN inn 0 DC {vcm - 0.5 * overdrive}
                ITAIL tail 0 DC {tail_current}
                M1 outp inp tail 0 NMOS W={w_in} L={l}
                M2 outn inn tail 0 NMOS W={w_in} L={l}
                RLP vdd outp {r_load}
                RLN vdd outn {r_load}
                CLOADP outp 0 {0.5 * cload}
                CLOADN outn 0 {0.5 * cload}
                BOUT out 0 V = 0.4*v(vdd) + 6*(v(outn)-v(outp))
                COUT out 0 {0.25 * cload}
                .model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)

                .control
                tran 20p 24n
                wrdata tran_in.csv time v(inp)
                wrdata tran_out.csv time v(out)
                quit
                .endc
                .end
                """

    def _build_llm_netlist(self, topology, sizing, constraints, memory: SharedMemory = None):
        if self.llm is None:
            return None

        analyses = []
        if memory is not None:
            analyses = ((memory.read("case_metadata") or {}).get("simulation_plan") or {}).get("analyses") or []

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
            - include at least one useful analysis (prefer these analyses when possible: {analyses})
            - include .control / run / quit if useful
            - include wrdata statements when possible
            - include .end
            - do not explain anything outside the netlist
            """
        result = self.llm.generate(prompt)
        if memory is not None:
            memory.append_history(
                "llm_call",
                {
                    "agent": "NetlistAgent",
                    "task": "single_topology_netlist",
                    "ok": bool(result),
                },
            )

        if isinstance(result, dict):
            return result.get("raw_text") or result.get("netlist")
        return str(result)

    def _build_composite_pipeline_netlist(self, memory: SharedMemory, sizing: dict, constraints: dict):
        plan = memory.read("topology_plan") or {}
        stages = sizing.get("stages") or plan.get("stages") or []
        analyses = ((memory.read("case_metadata") or {}).get("simulation_plan") or {}).get("analyses") or ["op", "ac", "tran"]

        if self.llm is not None:
            llm_netlist = self._build_llm_composite_netlist(stages, sizing, constraints, analyses, memory=memory)
            llm_markers = self._extract_stage_markers(llm_netlist or "")
            strict_markers = os.getenv("STRICT_COMPOSITE_STAGE_MARKERS", "0").strip() == "1"
            if (
                llm_netlist
                and ".end" in llm_netlist.lower()
                and (
                    (not strict_markers)
                    or (llm_markers and len(llm_markers) >= len(stages))
                )
            ):
                return llm_netlist, "llm_composite"

        fallback_netlist = self._build_deterministic_composite_netlist(stages, sizing, constraints, analyses)
        return fallback_netlist, "composite_fallback"

    def _build_llm_composite_netlist(self, stages, sizing, constraints, analyses, memory: SharedMemory = None):
        prompt = f"""
            You are generating an ngspice netlist for a multi-stage analog circuit.
            Keep the topology-based structure from the stage plan and connect stages in cascade.

            Stage plan:
            {stages}

            Composite sizing:
            {sizing}

            Constraints:
            {constraints}

            Planned analyses:
            {analyses}

            Return ONLY a valid ngspice netlist.
            Requirements:
            - one top-level input node named in, one final output node named out
            - preserve stage order from the stage plan
            - include .control with the planned analyses
            - include wrdata statements for out (ac_out.csv and/or tran_out.csv)
            - include .end
            """
        result = self.llm.generate(prompt)
        if memory is not None:
            memory.append_history(
                "llm_call",
                {
                    "agent": "NetlistAgent",
                    "task": "composite_netlist",
                    "ok": bool(result),
                },
            )
        if isinstance(result, dict):
            return result.get("raw_text") or result.get("netlist")
        return str(result) if result is not None else None

    def _build_deterministic_composite_netlist(self, stages, sizing, constraints, analyses):
        if not stages:
            stages = [{"name": "stage1", "topology": "common_source_res_load", "sizing": {}}]

        vin_ac = float(constraints.get("vin_ac", 1e-3))
        vin_dc = float(constraints.get("vin_dc", constraints.get("vin_cm_dc", 0.0)))
        vin_step = float(constraints.get("vin_step", 0.05))
        vdd = float(constraints.get("supply_v", 1.8))
        interstage_r = float(sizing.get("interstage_res_ohm", 2000.0))
        interstage_c = float(sizing.get("interstage_cap_f", 0.5e-12))
        ac_stop_hz = float(constraints.get("ac_stop_hz", max(1e7, 50.0 * float(constraints.get("target_bw_hz", 1e6)))))
        tran_step = float(constraints.get("tran_step_s", 1e-9))
        tran_stop = float(constraints.get("tran_stop_s", 5e-6))
        coupling_cap = max(interstage_c * 8.0, 0.5e-12)
        gate_bias_default = float(constraints.get("vin_dc", constraints.get("vin_cm_dc", 0.8)))

        lines = [
            "* Composite multi-stage topology pipeline",
            f"VDD vdd 0 DC {vdd}",
            f"VIN in 0 DC {vin_dc} AC {vin_ac} PULSE({vin_dc} {vin_dc + vin_step} 0 2n 2n 100n 200n)",
            ".model NMOS NMOS (LEVEL=1 VTO=0.5 KP=200u LAMBDA=0.02)",
            ".model PMOS PMOS (LEVEL=1 VTO=-0.5 KP=80u LAMBDA=0.02)",
            "",
        ]

        prev_node = "in"
        for idx, stage in enumerate(stages):
            stage_name = stage.get("name") or f"stage{idx + 1}"
            stage_topology = stage.get("topology") or "common_source_res_load"
            stage_sizing = stage.get("sizing") or {}
            stage_constraints = dict(constraints)
            stage_constraints.update(stage.get("constraints") or {})
            out_node = "out" if idx == len(stages) - 1 else f"n{idx + 1}"

            lines.append(
                f"{self.STAGE_MARKER_PREFIX} idx={idx + 1} name={stage_name} "
                f"topology={stage_topology} input={prev_node} output={out_node}"
            )
            lines.extend(
                self._emit_composite_stage(
                    stage_idx=idx + 1,
                    topology=stage_topology,
                    input_node=prev_node,
                    output_node=out_node,
                    stage_sizing=stage_sizing,
                    stage_constraints=stage_constraints,
                    global_constraints=constraints,
                    interstage_r=interstage_r,
                    interstage_c=interstage_c,
                    coupling_cap=coupling_cap,
                    gate_bias_default=gate_bias_default,
                )
            )
            lines.append("")

            prev_node = out_node

        lines.append("")
        lines.append(".control")
        lines.append("set wr_singlescale")
        if "op" in analyses:
            lines.append("op")
        if "ac" in analyses:
            lines.append(f"ac dec 200 1 {ac_stop_hz}")
            lines.append("wrdata ac_out.csv frequency vm(out)")
        if "dc" in analyses:
            lines.append("dc VIN 0 1.0 0.01")
            lines.append("wrdata dc_out.csv v(out)")
        if "tran" in analyses:
            lines.append(f"tran {tran_step} {tran_stop}")
            lines.append("wrdata tran_in.csv time v(in)")
            lines.append("wrdata tran_out.csv time v(out)")
        lines.append("quit")
        lines.append(".endc")
        lines.append(".end")
        return "\n".join(lines) + "\n"

    def _estimate_stage_gain(self, topology, stage_sizing, stage_constraints, global_constraints):
        if stage_sizing.get("stage_gain_linear") is not None:
            try:
                return float(stage_sizing.get("stage_gain_linear"))
            except Exception:
                pass

        gm = stage_sizing.get("gm_target")
        rd = stage_sizing.get("R_D")
        if gm is not None and rd is not None:
            try:
                gain = max(float(gm) * float(rd), 0.1)
                return min(gain, 5e3)
            except Exception:
                pass

        if topology == "common_drain":
            return 0.85
        if "mirror" in topology:
            return 1.0
        if "opamp" in topology or topology == "two_stage_miller":
            return 100.0

        target_gain_db = (
            stage_constraints.get("target_gain_db")
            if stage_constraints.get("target_gain_db") is not None
            else global_constraints.get("target_gain_db")
        )
        if target_gain_db is not None:
            try:
                gain = 10 ** (float(target_gain_db) / 20.0)
                return min(max(gain, 0.1), 5e3)
            except Exception:
                pass
        return 8.0

    def _emit_composite_stage(
        self,
        stage_idx,
        topology,
        input_node,
        output_node,
        stage_sizing,
        stage_constraints,
        global_constraints,
        interstage_r,
        interstage_c,
        coupling_cap,
        gate_bias_default,
    ):
        lines = []
        topo = (topology or "").lower()

        if "lowpass" in topo:
            r_ohm = float(stage_sizing.get("R_ohm", max(interstage_r, 100.0)))
            c_f = float(stage_sizing.get("C_f", interstage_c))
            lines.append(f"RLP{stage_idx} {input_node} {output_node} {r_ohm}")
            lines.append(f"CLP{stage_idx} {output_node} 0 {c_f}")
            return lines

        if "highpass" in topo:
            r_ohm = float(stage_sizing.get("R_ohm", max(interstage_r, 100.0)))
            c_f = float(stage_sizing.get("C_f", interstage_c))
            lines.append(f"CHP{stage_idx} {input_node} {output_node} {c_f}")
            lines.append(f"RHP{stage_idx} {output_node} 0 {r_ohm}")
            return lines

        if "bandpass" in topo:
            l_h = float(stage_sizing.get("L_h", 100e-6))
            c_f = float(stage_sizing.get("C_f", 1e-9))
            r_ohm = float(stage_sizing.get("R_ohm", max(interstage_r, 100.0)))
            mid_node = f"nbp{stage_idx}"
            lines.append(f"LBP{stage_idx} {input_node} {mid_node} {l_h}")
            lines.append(f"CBP{stage_idx} {mid_node} {output_node} {c_f}")
            lines.append(f"RBP{stage_idx} {output_node} 0 {r_ohm}")
            return lines

        if topo == "common_drain":
            gate_node = f"g{stage_idx}"
            lines.extend(self._compose_gate_drive(stage_idx, input_node, gate_node, coupling_cap, gate_bias_default))
            w = float(stage_sizing.get("W_m", stage_sizing.get("W_in", 2e-6)))
            l = float(stage_sizing.get("L_m", stage_sizing.get("L_in", 180e-9)))
            rs = float(stage_sizing.get("R_source", max(500.0, interstage_r)))
            lines.append(f"MSF{stage_idx} vdd {gate_node} {output_node} 0 NMOS W={w} L={l}")
            lines.append(f"RSF{stage_idx} {output_node} 0 {rs}")
            lines.append(f"CSTG{stage_idx} {output_node} 0 {max(interstage_c, 1e-15)}")
            return lines

        if topo == "common_gate":
            vbias = float(stage_sizing.get("Vbias", stage_constraints.get("Vbias", 1.0)))
            w = float(stage_sizing.get("W_m", stage_sizing.get("W_in", 2e-6)))
            l = float(stage_sizing.get("L_m", stage_sizing.get("L_in", 180e-9)))
            rd = float(stage_sizing.get("R_D", max(interstage_r, 1000.0)))
            lines.append(f"VBG{stage_idx} vbg{stage_idx} 0 DC {vbias}")
            lines.append(f"MCG{stage_idx} {output_node} vbg{stage_idx} {input_node} 0 NMOS W={w} L={l}")
            lines.append(f"RCG{stage_idx} vdd {output_node} {rd}")
            lines.append(f"CSTG{stage_idx} {output_node} 0 {max(interstage_c, 1e-15)}")
            return lines

        if topo == "diff_pair":
            gate_node = f"gp{stage_idx}"
            lines.extend(self._compose_gate_drive(stage_idx, input_node, gate_node, coupling_cap, gate_bias_default))
            vicm = float(stage_constraints.get("vicm_v", global_constraints.get("vicm_v", gate_bias_default)))
            i_tail = float(stage_sizing.get("I_tail", max(stage_sizing.get("tail_current_a", 0.0), 60e-6)))
            rload = float(stage_sizing.get("R_load", max(interstage_r, 3000.0)))
            w_in = float(stage_sizing.get("W_in", 2e-6))
            l_in = float(stage_sizing.get("L_in", 180e-9))
            w_tail = float(stage_sizing.get("W_tail", 1.2 * w_in))
            l_tail = float(stage_sizing.get("L_tail", l_in))
            lines.append(f"VINREF{stage_idx} inref{stage_idx} 0 DC {vicm}")
            lines.append(f"ITAIL{stage_idx} tail{stage_idx} 0 DC {i_tail}")
            lines.append(f"MDP1_{stage_idx} outp{stage_idx} {gate_node} tail{stage_idx} 0 NMOS W={w_in} L={l_in}")
            lines.append(f"MDP2_{stage_idx} outn{stage_idx} inref{stage_idx} tail{stage_idx} 0 NMOS W={w_in} L={l_in}")
            lines.append(f"MTAIL{stage_idx} tail{stage_idx} vtail{stage_idx} 0 0 NMOS W={w_tail} L={l_tail}")
            lines.append(f"VTAIL{stage_idx} vtail{stage_idx} 0 DC 0.85")
            lines.append(f"RLP{stage_idx} vdd outp{stage_idx} {rload}")
            lines.append(f"RLN{stage_idx} vdd outn{stage_idx} {rload}")
            lines.append(f"ROUT{stage_idx} {output_node} outp{stage_idx} 1m")
            lines.append(f"CSTG{stage_idx} {output_node} 0 {max(interstage_c, 1e-15)}")
            return lines

        gate_node = f"g{stage_idx}"
        source_node = f"s{stage_idx}"
        lines.extend(self._compose_gate_drive(stage_idx, input_node, gate_node, coupling_cap, gate_bias_default))
        w = float(
            stage_sizing.get(
                "W_m",
                stage_sizing.get(
                    "W_n",
                    stage_sizing.get("W_in", stage_sizing.get("W_pair", 2e-6)),
                ),
            )
        )
        l = float(
            stage_sizing.get(
                "L_m",
                stage_sizing.get(
                    "L_n",
                    stage_sizing.get("L_in", stage_sizing.get("L_pair", 180e-9)),
                ),
            )
        )
        rs = 0.0
        if topo == "source_degenerated_cs":
            rs = float(stage_sizing.get("R_S", max(50.0, 0.05 * interstage_r)))
        rd = stage_sizing.get("R_D")
        if rd is None:
            gain = self._estimate_stage_gain(topo, stage_sizing, stage_constraints, global_constraints)
            gm_guess = stage_sizing.get("gm_target", stage_sizing.get("gm_target_s"))
            if gm_guess is None and stage_sizing.get("I_bias") is not None:
                vov = float(stage_sizing.get("Vov_target", stage_sizing.get("Vov_target_v", 0.18)))
                gm_guess = 2.0 * float(stage_sizing.get("I_bias")) / max(vov, 1e-9)
            gm_guess = max(float(gm_guess or 1e-3), 1e-6)
            rd = max(1000.0, min(500e3, gain / gm_guess))
        rd = float(rd)
        lines.append(f"MCS{stage_idx} {output_node} {gate_node} {source_node if rs > 0 else 0} 0 NMOS W={w} L={l}")
        if rs > 0:
            lines.append(f"RSRC{stage_idx} {source_node} 0 {rs}")
        lines.append(f"RLOAD{stage_idx} vdd {output_node} {rd}")
        lines.append(f"CSTG{stage_idx} {output_node} 0 {max(interstage_c, 1e-15)}")
        return lines

    def _compose_gate_drive(self, stage_idx, input_node, gate_node, coupling_cap, gate_bias_default):
        lines = [
            f"RIN{stage_idx} {input_node} {gate_node} 1",
            f"VGBIAS{stage_idx} vgb{stage_idx} 0 DC {gate_bias_default}",
            f"RGBIAS{stage_idx} {gate_node} vgb{stage_idx} 5e6",
        ]
        return lines
