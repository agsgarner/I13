import importlib.util
import os
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class LLMBackendResolution:
    configured_backend: str
    resolved_backend: str
    ok: bool
    fallback_used: bool
    message: str
    llm: Optional[Any] = None


def configured_llm_backend() -> str:
    raw = os.getenv("LLM_BACKEND", "").strip().lower()
    if raw:
        aliases = {
            "stub": "local_stub",
            "local": "local_stub",
            "none": "rule_based",
            "deterministic": "rule_based",
            "rules": "rule_based",
            "rules_only": "rule_based",
        }
        return aliases.get(raw, raw)

    # Backward-compatible env handling.
    if os.getenv("USE_OPENAI", "0").strip() == "1":
        return "openai"

    return "rule_based"


def _resolve_openai_backend(instantiate: bool = True) -> LLMBackendResolution:
    has_openai_pkg = importlib.util.find_spec("openai") is not None
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

    missing = []
    if not has_openai_pkg:
        missing.append("python package 'openai' not installed")
    if not api_key:
        missing.append("OPENAI_API_KEY not set")

    if missing:
        return LLMBackendResolution(
            configured_backend="openai",
            resolved_backend="rule_based",
            ok=True,
            fallback_used=True,
            message=(
                "Configured backend 'openai' is unavailable ("
                + "; ".join(missing)
                + "). Falling back to deterministic rule-based planning."
            ),
            llm=None,
        )

    if not instantiate:
        return LLMBackendResolution(
            configured_backend="openai",
            resolved_backend="openai",
            ok=True,
            fallback_used=False,
            message=f"OpenAI backend is configured and ready (model={model}).",
            llm=None,
        )

    try:
        from llm.openai_llm import OpenAILLM

        llm = OpenAILLM(
            model=model,
            temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.2")),
        )
        return LLMBackendResolution(
            configured_backend="openai",
            resolved_backend="openai",
            ok=True,
            fallback_used=False,
            message=f"Using OpenAI backend (model={model}).",
            llm=llm,
        )
    except Exception as exc:
        return LLMBackendResolution(
            configured_backend="openai",
            resolved_backend="rule_based",
            ok=True,
            fallback_used=True,
            message=(
                "OpenAI backend failed to initialize "
                f"({exc}). Falling back to deterministic rule-based planning."
            ),
            llm=None,
        )


def resolve_llm_backend(instantiate: bool = True) -> LLMBackendResolution:
    configured = configured_llm_backend()

    if configured == "openai":
        return _resolve_openai_backend(instantiate=instantiate)

    if configured == "local_stub":
        if instantiate:
            from llm.local_llm_stub import LocalLLMStub

            llm = LocalLLMStub()
        else:
            llm = None
        return LLMBackendResolution(
            configured_backend="local_stub",
            resolved_backend="local_stub",
            ok=True,
            fallback_used=False,
            message="Using LocalLLMStub backend.",
            llm=llm,
        )

    if configured == "rule_based":
        return LLMBackendResolution(
            configured_backend="rule_based",
            resolved_backend="rule_based",
            ok=True,
            fallback_used=False,
            message="Using deterministic rule-based planner (no external LLM backend).",
            llm=None,
        )

    return LLMBackendResolution(
        configured_backend=configured,
        resolved_backend="rule_based",
        ok=True,
        fallback_used=True,
        message=(
            f"Unknown LLM_BACKEND='{configured}'. "
            "Falling back to deterministic rule-based planner."
        ),
        llm=None,
    )
