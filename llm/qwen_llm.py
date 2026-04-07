import json
import os
import re

import requests

from core.llm_interface import LLMInterface


class QwenLLM(LLMInterface):
    def __init__(self, model="qwen-turbo", api_key=None, temperature=0.2):
        self.api_key = api_key or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError("Set QWEN_API_KEY or DASHSCOPE_API_KEY in your environment.")

        self.model = model
        self.temperature = temperature

        preferred_base_url = os.getenv("QWEN_BASE_URL")
        self.base_urls = [
            preferred_base_url,
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        ]
        self.base_urls = [url for url in self.base_urls if url]

    def generate(self, prompt: str):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
        }

        last_error = None
        for base_url in self.base_urls:
            response = requests.post(base_url, json=payload, headers=headers, timeout=60)
            if response.ok:
                data = response.json()
                text = data["choices"][0]["message"]["content"].strip()
                return self._parse_json_or_text(text)

            try:
                error_payload = response.json()
            except Exception:
                error_payload = response.text
            last_error = f"Qwen API error {response.status_code} at {base_url}: {error_payload}"

        raise RuntimeError(last_error or "Qwen API request failed")

    def _parse_json_or_text(self, text: str):
        try:
            return json.loads(text)
        except Exception:
            pass

        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        return {"raw_text": text}