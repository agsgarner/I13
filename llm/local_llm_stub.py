# I13/llm/local_llm_stub.py

from core.llm_interface import LLMInterface


class LocalLLMStub(LLMInterface):
    """
    Temporary mock LLM.
    This simulates topology selection until real transformer is integrated.
    """

    def generate(self, prompt: str):

        prompt_lower = prompt.lower()

        if "lowpass" in prompt_lower:
            return {"topology": "rc_lowpass", "confidence": 0.92}

        if "differential" in prompt_lower:
            return {"topology": "diff_pair", "confidence": 0.88}

        if "current mirror" in prompt_lower:
            return {"topology": "current_mirror", "confidence": 0.85}

        return {"topology": "common_source_res_load", "confidence": 0.75}