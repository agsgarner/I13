# llm_interface.py

from typing import Dict, Any


class LLMInterface:
    def generate(self, prompt: str) -> Dict[str, Any]:
        raise NotImplementedError
