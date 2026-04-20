# I13/llm/local_llm_stub.py

from core.llm_interface import LLMInterface


class LocalLLMStub(LLMInterface):
    """
    Temporary mock LLM.
    Reliable fallback for sponsor demos when API/network is unavailable.
    """

    def generate(self, prompt: str):
        prompt_lower = prompt.lower()

        if "planning a multi-stage analog circuit pipeline" in prompt_lower:
            return {
                "mode": "composite",
                "confidence": 0.82,
                "reasoning": "Use a gain stage followed by a buffer stage for robust first-pass convergence.",
                "stages": [
                    {"name": "stage1", "topology": "common_source_res_load", "role": "voltage_gain"},
                    {"name": "stage2", "topology": "common_drain", "role": "output_buffer"},
                ],
            }

        if (
            "available topology keys" in prompt_lower
            and "return json only" in prompt_lower
        ) or "choose the single best topology key" in prompt_lower:
            if "low-pass" in prompt_lower or "lowpass" in prompt_lower:
                return {
                    "topology": "rc_lowpass",
                    "confidence": 0.95,
                    "reasoning": (
                        "An RC low-pass filter is the simplest and most direct topology "
                        "for a first-order low-pass response near the requested cutoff."
                    ),
                }

            if "differential" in prompt_lower:
                return {
                    "topology": "diff_pair",
                    "confidence": 0.88,
                    "reasoning": "A differential pair is appropriate for differential analog amplification tasks.",
                }

            if "current mirror" in prompt_lower:
                return {
                    "topology": "current_mirror",
                    "confidence": 0.85,
                    "reasoning": "A current mirror is the standard topology for current replication and biasing.",
                }

            if "source follower" in prompt_lower or "common-drain" in prompt_lower:
                return {
                    "topology": "common_drain",
                    "confidence": 0.84,
                    "reasoning": "A common-drain stage is the standard MOS buffer topology.",
                }

            if "common-gate" in prompt_lower:
                return {
                    "topology": "common_gate",
                    "confidence": 0.82,
                    "reasoning": "A common-gate topology is appropriate for low-input-impedance wideband gain stages.",
                }

            if "nand" in prompt_lower:
                return {
                    "topology": "nand2_cmos",
                    "confidence": 0.9,
                    "reasoning": "A CMOS NAND gate is the natural transistor-level implementation for the request.",
                }

            return {
                "topology": "common_source_res_load",
                "confidence": 0.75,
                "reasoning": "A common-source stage is a reasonable default for simple voltage amplification.",
            }

        if "allocating first-pass sizing intent for a cascaded analog pipeline" in prompt_lower:
            return {
                "stage_constraints": [
                    {"target_gain_db": 14.0, "target_bw_hz": 3.0e6},
                    {"target_gain_db": 10.0, "target_bw_hz": 2.0e6},
                    {"target_gm_s": 2.5e-3},
                ],
                "interstage_res_ohm": 2200.0,
                "interstage_cap_f": 0.6e-12,
                "notes": [
                    "Assigned moderate gain to the first two stages and reserved output headroom for the buffer.",
                ],
            }

        if "suggest multiplicative updates for existing numeric sizing keys only" in prompt_lower:
            return {
                "updates": {},
                "notes": ["Stub mode: no additional LLM refinement updates suggested."],
            }

        if (
            "return only a valid ngspice netlist" in prompt_lower
            and "multi-stage analog circuit" in prompt_lower
        ):
            return {
                "raw_text": """* Stub composite netlist
VDD vdd 0 DC 1.8
VIN in 0 DC 0.8 AC 1m PULSE(0.8 0.85 0 2n 2n 100n 200n)
E1 n1 0 in 0 20
R1 n1 0 2k
C1 n1 0 500f
E2 out 0 n1 0 0.9
R2 out 0 2k
C2 out 0 500f
.control
set wr_singlescale
op
ac dec 100 1 1e8
wrdata ac_out.csv frequency vm(out)
tran 1n 5u
wrdata tran_in.csv time v(in)
wrdata tran_out.csv time v(out)
quit
.endc
.end
"""
            }

        if "return only a valid ngspice netlist" in prompt_lower:
            return {
                "raw_text": """* Generic fallback netlist
V1 in 0 DC 0 AC 1
R1 in out 1k
C1 out 0 1n
.ac dec 50 1 1e6
.control
run
wrdata ac_out.csv frequency vm(out)
quit
.endc
.end
"""
            }

        return {
            "raw_text": "Unsupported prompt for LocalLLMStub."
        }
