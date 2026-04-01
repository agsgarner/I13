# I13/llm/local_llm_stub.py

from core.llm_interface import LLMInterface


class LocalLLMStub(LLMInterface):
    """
    Temporary mock LLM.
    Reliable fallback for sponsor demos when API/network is unavailable.
    """

    def generate(self, prompt: str):
        prompt_lower = prompt.lower()

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
