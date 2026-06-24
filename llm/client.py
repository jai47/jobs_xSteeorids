"""
Single abstraction for all LLM calls.
Primary: Anthropic Claude claude-sonnet-4-20250514
Fallback: OpenCode Zen (OpenAI-compatible), then OpenAI GPT-4o
"""

from __future__ import annotations

import json
import logging
import uuid

import anthropic
import openai
from sqlalchemy.orm import Session

from api.deps import LLMError
from config import settings
from db.models import LLMUsage

log = logging.getLogger(__name__)

ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
OPENAI_MODEL = "gpt-4o"


def _log_usage(
    session: Session,
    user_id: uuid.UUID,
    provider: str,
    model: str,
    purpose: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Persist token usage for cost tracking."""
    session.add(
        LLMUsage(
            user_id=user_id,
            provider=provider,
            model=model,
            call_purpose=purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    )
    session.flush()


def _call_openai_compatible(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    provider: str,
    prompt: str,
    purpose: str,
    user_id: uuid.UUID,
    session: Session,
    max_tokens: int,
) -> str:
    """Call an OpenAI-compatible chat completions endpoint."""
    client_kwargs: dict[str, str] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = openai.OpenAI(**client_kwargs)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content or ""
    usage = response.usage
    _log_usage(
        session,
        user_id,
        provider,
        model,
        purpose,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )
    return text


def _provider_error(provider: str, exc: Exception) -> str:
    """Format a provider failure for user-facing errors."""
    message = str(exc).strip()
    if len(message) > 240:
        message = message[:237] + "..."
    return f"{provider}: {message}"


def call_llm(
    prompt: str,
    purpose: str,
    user_id: uuid.UUID,
    session: Session,
    max_tokens: int = 2000,
) -> str:
    """Return raw LLM text. Raises LLMError after all retries."""
    failures: list[str] = []

    if settings.anthropic_api_key:
        for attempt in range(3):
            try:
                client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
                response = client.messages.create(
                    model=ANTHROPIC_MODEL,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text
                _log_usage(
                    session,
                    user_id,
                    "anthropic",
                    ANTHROPIC_MODEL,
                    purpose,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )
                return text
            except Exception as exc:
                log.warning(
                    "Anthropic call failed (attempt %s/3): %s",
                    attempt + 1,
                    exc,
                )
                if attempt == 2:
                    failures.append(_provider_error("Anthropic", exc))

    if settings.opencode_api_key:
        try:
            return _call_openai_compatible(
                api_key=settings.opencode_api_key,
                base_url=settings.opencode_base_url,
                model=settings.opencode_model,
                provider="opencode",
                prompt=prompt,
                purpose=purpose,
                user_id=user_id,
                session=session,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            log.error("OpenCode call failed: %s", exc)
            failures.append(_provider_error("OpenCode Zen", exc))

    if settings.local_llm_base_url:
        try:
            return _call_openai_compatible(
                api_key=settings.local_llm_api_key or "ollama",
                base_url=settings.local_llm_base_url,
                model=settings.local_llm_model,
                provider="local",
                prompt=prompt,
                purpose=purpose,
                user_id=user_id,
                session=session,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            log.error("Local LLM call failed: %s", exc)
            failures.append(_provider_error("Local LLM", exc))

    if settings.openai_api_key:
        try:
            return _call_openai_compatible(
                api_key=settings.openai_api_key,
                base_url=None,
                model=OPENAI_MODEL,
                provider="openai",
                prompt=prompt,
                purpose=purpose,
                user_id=user_id,
                session=session,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            log.error("OpenAI fallback failed: %s", exc)
            failures.append(_provider_error("OpenAI", exc))

    if failures:
        raise LLMError("LLM providers unavailable — " + "; ".join(failures))

    raise LLMError(
        "No LLM API keys configured. Set OPENCODE_API_KEY and/or ANTHROPIC_API_KEY in .env."
    )


def parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)
