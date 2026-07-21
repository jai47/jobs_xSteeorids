"""Persist deployment-wide LLM provider preference (API keys stay in .env)."""

from __future__ import annotations

import json
from pathlib import Path

from config import settings

_RUNTIME_PATH = Path(__file__).resolve().parent.parent / "data" / "llm_runtime.json"

VALID_PROVIDERS = frozenset(
    {
        "auto",
        "anthropic",
        "deepseek",
        "google",
        "kimi",
        "azure",
        "aws",
        "opencode",
        "local",
        "openai",
    }
)


def get_selected_provider() -> str:
    """Return UI/runtime override, else LLM_PROVIDER from env, default auto."""
    if _RUNTIME_PATH.is_file():
        try:
            data = json.loads(_RUNTIME_PATH.read_text(encoding="utf-8"))
            provider = str(data.get("provider", "")).strip().lower()
            if provider in VALID_PROVIDERS:
                return provider
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    env_provider = settings.llm_provider.strip().lower()
    if env_provider in VALID_PROVIDERS:
        return env_provider
    return "auto"


def set_selected_provider(provider: str) -> str:
    """Save provider preference to disk; returns normalized id."""
    normalized = provider.strip().lower()
    if normalized not in VALID_PROVIDERS:
        raise ValueError(f"Unknown LLM provider: {provider}")
    _RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RUNTIME_PATH.write_text(
        json.dumps({"provider": normalized}, indent=2) + "\n",
        encoding="utf-8",
    )
    return normalized
