# I13/llm/local_llm_stub.py

from core.llm_interface import LLMInterface


class LocalLLMStub(LLMInterface):
    """
    Temporary mock LLM.
    This simulates topology selection for offline testing when Qwen is unavailable.
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

        return {"topology": "unknown", "confidence": 0.1}

        return {"topology": "common_source_res_load", "confidence": 0.75}