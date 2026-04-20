# I13/llm/openai_llm.py

import os
import json
import re
from openai import OpenAI

from core.llm_interface import LLMInterface


class OpenAILLM(LLMInterface):
    def __init__(self, model="gpt-5.4-mini", api_key=None, temperature=0.2):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Set OPENAI_API_KEY in your environment.")
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature

    def generate(self, prompt: str):
        response = self.client.responses.create(
            model=self.model,
            input=prompt,
            temperature=self.temperature,
        )
        text = response.output_text.strip()
        return self._parse_json_or_text(text)

    def _parse_json_or_text(self, text: str):
        try:
            return json.loads(text)
        except Exception:
            pass

        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass

        return {"raw_text": text}
    
