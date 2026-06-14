"""
Single abstraction for all LLM calls.
Primary: Anthropic Claude claude-sonnet-4-20250514
Fallback: OpenAI GPT-4o after 3 failed Anthropic retries
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


def call_llm(
    prompt: str,
    purpose: str,
    user_id: uuid.UUID,
    session: Session,
    max_tokens: int = 2000,
) -> str:
    """Return raw LLM text. Raises LLMError after all retries."""
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
                    break

    if settings.openai_api_key:
        try:
            client = openai.OpenAI(api_key=settings.openai_api_key)
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content or ""
            usage = response.usage
            _log_usage(
                session,
                user_id,
                "openai",
                OPENAI_MODEL,
                purpose,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            )
            return text
        except Exception as exc:
            log.error("OpenAI fallback failed: %s", exc)
            raise LLMError("LLM providers unavailable") from exc

    raise LLMError("No LLM API keys configured")


def parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)
