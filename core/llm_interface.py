# I13/core/llm_interface.py

from typing import Any


class LLMInterface:
    def generate(self, prompt: str) -> Any:
        raise NotImplementedError
