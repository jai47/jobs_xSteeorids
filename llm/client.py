"""
Single abstraction for all LLM calls.
Provider order respects LLM_PROVIDER / UI selection, then falls through the chain on failure.
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.orm import Session

from api.deps import LLMError
from llm.providers import (
    call_provider,
    is_provider_configured,
    provider_error_label,
    resolve_provider_chain,
)

log = logging.getLogger(__name__)


def _provider_error(provider_id: str, exc: Exception) -> str:
    message = str(exc).strip()
    if len(message) > 240:
        message = message[:237] + "..."
    return f"{provider_error_label(provider_id)}: {message}"


def call_llm(
    prompt: str,
    purpose: str,
    user_id: uuid.UUID,
    session: Session,
    max_tokens: int = 2000,
) -> str:
    """Return raw LLM text. Raises LLMError after all retries."""
    failures: list[str] = []
    chain = resolve_provider_chain()
    tried: set[str] = set()

    for provider_id in chain:
        if provider_id in tried or not is_provider_configured(provider_id):
            continue
        tried.add(provider_id)

        attempts = 3 if provider_id == "anthropic" else 1
        for attempt in range(attempts):
            try:
                return call_provider(
                    provider_id,
                    prompt,
                    purpose,
                    user_id,
                    session,
                    max_tokens,
                )
            except Exception as exc:
                log.warning(
                    "%s call failed (attempt %s/%s): %s",
                    provider_error_label(provider_id),
                    attempt + 1,
                    attempts,
                    exc,
                )
                if attempt == attempts - 1:
                    failures.append(_provider_error(provider_id, exc))

    if failures:
        raise LLMError("LLM providers unavailable — " + "; ".join(failures))

    raise LLMError(
        "No LLM API keys configured. Add provider keys to .env "
        "(see Settings → LLM for supported providers)."
    )


def parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)
