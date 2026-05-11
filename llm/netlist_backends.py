import importlib.util
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class NetlistBackendResult:
    backend_used: str
    prompt_sent: str = ""
    raw_response: str = ""
    cleaned_netlist: str = ""
    fallback_reason: str = ""
    warnings: list[str] = field(default_factory=list)


class NetlistGenerationBackend:
    name = "base"

    def available(self) -> tuple[bool, str]:
        return False, "backend not implemented"

    def generate(self, prompt: str) -> Any:
        raise NotImplementedError


class HuggingFaceSpaceNetlistBackend(NetlistGenerationBackend):
    name = "huggingface_gradio"

    def __init__(self, space_id: Optional[str] = None, token: Optional[str] = None):
        self.space_id = space_id or os.getenv("HF_SPACE_ID", "potatoman869/spice_netlist-generator")
        self.token = token if token is not None else os.getenv("HF_TOKEN", "").strip()

    def available(self) -> tuple[bool, str]:
        if os.getenv("USE_HF_NETLIST", "0").strip() != "1":
            return False, "USE_HF_NETLIST is not 1"
        if importlib.util.find_spec("gradio_client") is None:
            return False, "python package 'gradio_client' is not installed"
        return True, f"HF Space configured: {self.space_id}"

    def generate(self, prompt: str) -> Any:
        from gradio_client import Client

        kwargs = {}
        if self.token:
            kwargs["hf_token"] = self.token
        client = Client(self.space_id, **kwargs)

        errors = []
        for call in (
            lambda: client.predict(prompt, api_name="/predict"),
            lambda: client.predict(prompt),
        ):
            try:
                return call()
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError("; ".join(errors) or "HF Space prediction failed")


class OpenAINetlistBackend(NetlistGenerationBackend):
    name = "openai"

    def __init__(self, llm: Any = None):
        self.llm = llm

    def available(self) -> tuple[bool, str]:
        if os.getenv("USE_OPENAI", "0").strip() != "1" and os.getenv("LLM_BACKEND", "").strip().lower() != "openai":
            return False, "USE_OPENAI is not 1 and LLM_BACKEND is not openai"
        if not os.getenv("OPENAI_API_KEY", "").strip():
            return False, "OPENAI_API_KEY is not set"
        if self.llm is not None:
            return True, "caller-provided OpenAI-capable LLM is available"
        if importlib.util.find_spec("openai") is None:
            return False, "python package 'openai' is not installed"
        return True, "OpenAI package and API key are available"

    def generate(self, prompt: str) -> Any:
        llm = self.llm
        if llm is None:
            from llm.openai_llm import OpenAILLM

            llm = OpenAILLM(
                model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
                temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.2")),
            )
        return llm.generate(prompt)


class DeterministicNetlistBackend(NetlistGenerationBackend):
    name = "local_deterministic"

    def __init__(self, builder: Callable[[], Optional[str]]):
        self.builder = builder

    def available(self) -> tuple[bool, str]:
        return True, "deterministic local netlist builder is always available"

    def generate(self, prompt: str) -> Any:
        return self.builder()


def stringify_backend_response(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, dict):
        for key in ("netlist", "raw_text", "text", "output", "response"):
            value = response.get(key)
            if value:
                return str(value)
        return str(response)
    if isinstance(response, (list, tuple)):
        for item in response:
            text = stringify_backend_response(item)
            if ".end" in text.lower() or _looks_like_spice(text):
                return text
        return "\n".join(str(item) for item in response)
    return str(response)


def cleanup_spice_netlist(raw_text: str, required_analyses=None) -> str:
    required_analyses = list(required_analyses or [])
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _extract_markdown_code_block(text)
    text = _strip_explanatory_lines(text)
    text = _ensure_single_end(text)
    text = _ensure_control_analyses(text, required_analyses)
    return text.strip() + "\n" if text.strip() else ""


def generate_netlist_with_backends(
    *,
    prompt: str,
    analyses: list[str],
    deterministic_builder: Callable[[], Optional[str]],
    llm: Any = None,
    validate: Optional[Callable[[str], Optional[str]]] = None,
) -> NetlistBackendResult:
    warnings = []
    fallback_reasons = []
    backends: list[NetlistGenerationBackend] = [
        HuggingFaceSpaceNetlistBackend(),
        OpenAINetlistBackend(llm=llm),
        DeterministicNetlistBackend(deterministic_builder),
    ]

    for backend in backends:
        available, reason = backend.available()
        if not available:
            if backend.name == "huggingface_gradio" and os.getenv("USE_HF_NETLIST", "0").strip() == "1":
                warning = f"[NetlistBackend] Hugging Face backend unavailable: {reason}. Falling back automatically."
                print(warning)
                warnings.append(warning)
            fallback_reasons.append(f"{backend.name}: {reason}")
            continue

        try:
            raw_response = stringify_backend_response(backend.generate(prompt))
            cleaned = cleanup_spice_netlist(raw_response, required_analyses=analyses)
            validation_error = validate(cleaned) if validate else None
            if cleaned and not validation_error:
                return NetlistBackendResult(
                    backend_used=backend.name,
                    prompt_sent=prompt,
                    raw_response=raw_response,
                    cleaned_netlist=cleaned,
                    fallback_reason="; ".join(fallback_reasons),
                    warnings=warnings,
                )
            fallback_reasons.append(
                f"{backend.name}: cleaned netlist invalid"
                + (f" ({validation_error})" if validation_error else "")
            )
        except Exception as exc:
            fallback_reasons.append(f"{backend.name}: {exc}")
            if backend.name != "local_deterministic":
                print(f"[NetlistBackend] {backend.name} failed: {exc}. Falling back automatically.")

    return NetlistBackendResult(
        backend_used="none",
        prompt_sent=prompt,
        fallback_reason="; ".join(fallback_reasons) or "all backends failed",
        warnings=warnings,
    )


def _extract_markdown_code_block(text: str) -> str:
    matches = re.findall(r"```(?:spice|ngspice|cir|netlist|text)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if not matches:
        return text
    for candidate in matches:
        if ".end" in candidate.lower() or _looks_like_spice(candidate):
            return candidate
    return matches[0]


def _looks_like_spice(text: str) -> bool:
    device_line = re.compile(r"^\s*[RCLVIMQXBEFGH]\w*\s+\S+\s+\S+", re.IGNORECASE | re.MULTILINE)
    directive = re.compile(r"^\s*\.(model|include|param|control|op|ac|dc|tran|end)\b", re.IGNORECASE | re.MULTILINE)
    return bool(device_line.search(text or "") or directive.search(text or ""))


def _strip_explanatory_lines(text: str) -> str:
    kept = []
    in_control = False
    started = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            if started:
                kept.append("")
            continue
        if line.startswith("```"):
            continue
        lower = line.lower()
        if lower.startswith(("#", "here is", "this netlist", "explanation", "note:")):
            continue
        if re.match(r"^[-*]\s+(this|the|it|use|run)\b", lower):
            continue
        if line.startswith(".control"):
            in_control = True
            started = True
            kept.append(line)
            continue
        if line.startswith(".endc"):
            in_control = False
            started = True
            kept.append(line)
            continue
        if in_control:
            kept.append(line)
            continue
        if _is_spice_line(line):
            started = True
            kept.append(line)
    return "\n".join(kept)


def _is_spice_line(line: str) -> bool:
    if line.startswith("*"):
        return True
    if re.match(r"^\.(model|include|lib|param|control|endc|end|op|ac|dc|tran|noise|ic|options)\b", line, re.IGNORECASE):
        return True
    if re.match(r"^[RCLVIMQXBEFGH]\w*\s+", line, re.IGNORECASE):
        return True
    return False


def _ensure_single_end(text: str) -> str:
    lines = []
    seen_end = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if re.match(r"^\.end\b", line, re.IGNORECASE):
            seen_end = True
            break
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    lines.append(".end")
    return "\n".join(lines) if seen_end or lines else ""


def _ensure_control_analyses(text: str, required_analyses: list[str]) -> str:
    if not text.strip():
        return ""
    lower = text.lower()
    missing = [name for name in required_analyses if name in {"op", "ac", "dc", "tran"} and not re.search(rf"^\s*{name}\b", lower, re.MULTILINE)]
    if not missing:
        return text
    lines = [line for line in text.splitlines() if not re.match(r"^\.end\b", line.strip(), re.IGNORECASE)]
    if ".control" not in lower:
        lines.extend(["", ".control"])
        if "op" in missing:
            lines.append("op")
        if "ac" in missing:
            lines.append("ac dec 50 1 1e6")
            lines.append("wrdata ac_out.csv frequency vm(out)")
        if "dc" in missing:
            lines.append("dc VIN 0 1 0.01")
            lines.append("wrdata dc_out.csv v(in) v(out)")
        if "tran" in missing:
            lines.append("tran 1n 1u")
            lines.append("wrdata tran_out.csv time v(out)")
        lines.extend(["quit", ".endc", ".end"])
        return "\n".join(lines)

    insert_at = len(lines)
    for idx, line in enumerate(lines):
        if re.match(r"^\.endc\b", line.strip(), re.IGNORECASE):
            insert_at = idx
            break
    additions = []
    for name in missing:
        if name == "op":
            additions.append("op")
        elif name == "ac":
            additions.extend(["ac dec 50 1 1e6", "wrdata ac_out.csv frequency vm(out)"])
        elif name == "dc":
            additions.extend(["dc VIN 0 1 0.01", "wrdata dc_out.csv v(in) v(out)"])
        elif name == "tran":
            additions.extend(["tran 1n 1u", "wrdata tran_out.csv time v(out)"])
    lines[insert_at:insert_at] = additions
    lines.append(".end")
    return "\n".join(lines)
