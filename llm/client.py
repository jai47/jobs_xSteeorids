"""
Single abstraction for all LLM calls.
Provider order respects per-user preference, then falls through the chain on failure.
Platform (server) keys debit app tokens only after a successful call; BYOK is free.
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.orm import Session

from api.deps import LLMError
from db.models import User
from llm.providers import (
    call_provider,
    is_provider_configured,
    provider_error_label,
    resolve_provider_chain,
)
from services.token_billing import charge_llm_call, enforce_balance, get_rates
from services.user_llm_keys import get_byok_model, get_decrypted_key

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
    """Return raw LLM text. Raises LLMError after all retries.

    Platform-key calls are charged only after a successful provider response.
    Failed attempts (and BYOK calls) do not deduct tokens.
    preferred_llm_provider=platform forces server .env keys only (token-billed).
    """
    user = session.get(User, user_id)
    preferred_raw = getattr(user, "preferred_llm_provider", None) if user else None
    preferred_norm = (
        preferred_raw.strip().lower() if isinstance(preferred_raw, str) and preferred_raw.strip() else "auto"
    )
    platform_only = preferred_norm == "platform"
    chain = resolve_provider_chain("auto" if platform_only else preferred_norm)
    failures: list[str] = []
    tried: set[str] = set()

    byok: dict[str, str] = {}
    byok_models: dict[str, str] = {}
    if not platform_only:
        for provider_id in chain:
            key = get_decrypted_key(session, user_id, provider_id)
            if key:
                byok[provider_id] = key
                model = get_byok_model(session, user_id, provider_id)
                if model:
                    byok_models[provider_id] = model

    # If the first usable provider is platform (not BYOK), ensure balance up front.
    platform_needed = False
    for provider_id in chain:
        user_key = byok.get(provider_id)
        if is_provider_configured(provider_id, user_api_key=user_key):
            platform_needed = not bool(user_key)
            break

    if platform_needed and isinstance(user, User):
        rates = get_rates(session)
        enforce_balance(session, user, int(rates["llm_call_tokens"]))

    for provider_id in chain:
        if provider_id in tried:
            continue
        user_key = byok.get(provider_id)
        if not is_provider_configured(provider_id, user_api_key=user_key):
            continue

        # Falling back from BYOK to platform — check balance before calling.
        if not user_key and isinstance(user, User) and not platform_needed:
            rates = get_rates(session)
            enforce_balance(session, user, int(rates["llm_call_tokens"]))

        tried.add(provider_id)
        attempts = 3 if provider_id == "anthropic" else 1
        for attempt in range(attempts):
            try:
                text = call_provider(
                    provider_id,
                    prompt,
                    purpose,
                    user_id,
                    session,
                    max_tokens,
                    api_key_override=user_key,
                    model_override=byok_models.get(provider_id) if user_key else None,
                )
                # Charge only after success, and only for platform keys.
                if not user_key and isinstance(user, User):
                    rates = get_rates(session)
                    if rates["llm_call_tokens"] > 0:
                        charge_llm_call(session, user, purpose)
                return text
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
        "No LLM API keys configured. Add your own keys in Settings → API keys, "
        "or ask an admin to configure platform providers."
    )


def parse_llm_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[: text.rfind("```")].strip()
    return json.loads(text)
