import json
from typing import Any, Dict, List

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from core.llm_interface import LLMInterface
from core.topology_library import TOPOLOGY_LIBRARY


class QwenLLM(LLMInterface):

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-1.5B-Instruct",
        max_new_tokens: int = 96,
        temperature: float = 0.2,
        top_p: float = 0.9,
    ):
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            dtype=(torch.float16 if torch.cuda.is_available() else torch.float32),
            device_map="auto",
        )

    def _extract_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()

        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass

        return {}

    def _fallback_topology(self, prompt: str) -> Dict[str, Any]:
        prompt_lower = prompt.lower()

        if "lowpass" in prompt_lower:
            return {"topology": "rc_lowpass", "confidence": 0.6}
        if "differential" in prompt_lower:
            return {"topology": "diff_pair", "confidence": 0.55}
        if "current mirror" in prompt_lower:
            return {"topology": "current_mirror", "confidence": 0.55}

        return {"topology": "unknown", "confidence": 0.1}

    def generate(self, prompt: str) -> Dict[str, Any]:
        allowed_topologies: List[str] = list(TOPOLOGY_LIBRARY.keys())

        system_prompt = (
            "You are an analog circuit assistant. "
            "Return only valid JSON with keys topology and confidence. "
            f"topology must be one of: {', '.join(allowed_topologies)}. "
            "confidence must be a number in [0, 1]."
        )

        chat = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        chat_inputs = self.tokenizer.apply_chat_template(
            chat,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )

        if isinstance(chat_inputs, torch.Tensor):
            chat_inputs = {"input_ids": chat_inputs}

        chat_inputs = {k: v.to(self.model.device) for k, v in chat_inputs.items()}

        do_sample = self.temperature > 0
        outputs = self.model.generate(
            **chat_inputs,
            max_new_tokens=self.max_new_tokens,
            do_sample=do_sample,
            temperature=(self.temperature if do_sample else None),
            top_p=(self.top_p if do_sample else None),
            pad_token_id=self.tokenizer.eos_token_id,
        )

        prompt_len = chat_inputs["input_ids"].shape[1]
        generated_ids = outputs[0][prompt_len:]
        raw_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
        parsed = self._extract_json(raw_text)

        topology = str(parsed.get("topology", "")).strip().lower()
        confidence = parsed.get("confidence", 0.1)

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.1

        confidence = max(0.0, min(1.0, confidence))

        if topology not in allowed_topologies:
            return self._fallback_topology(prompt)

        return {"topology": topology, "confidence": confidence}