"""Per-user BYOK LLM key storage and lookup."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import User, UserLlmKey
from llm.providers import (
    DEFAULT_CHAIN,
    PROVIDER_META,
    catalog_models_for,
    default_model_for,
    resolve_model_id,
)
from services.secret_box import decrypt_secret, encrypt_secret, key_hint

# Providers that accept a single API key string for BYOK.
BYOK_PROVIDERS = frozenset(
    {
        "groq",
        "anthropic",
        "deepseek",
        "google",
        "kimi",
        "opencode",
        "openai",
        "azure",
        "local",
    }
)


def list_user_keys(session: Session, user: User) -> list[dict]:
    rows = (
        session.execute(select(UserLlmKey).where(UserLlmKey.user_id == user.id))
        .scalars()
        .all()
    )
    by_provider = {row.provider: row for row in rows}
    providers = []
    for pid in DEFAULT_CHAIN:
        meta = PROVIDER_META[pid]
        row = by_provider.get(pid)
        models = catalog_models_for(pid)
        selected = None
        if row is not None:
            selected = resolve_model_id(pid, getattr(row, "model", None))
        elif models:
            selected = models[0]["id"]
        providers.append(
            {
                "id": pid,
                "label": meta.label,
                "byok_supported": pid in BYOK_PROVIDERS,
                "configured": row is not None,
                "key_hint": row.key_hint if row else None,
                "model": selected,
                "models": models,
                "env_keys": list(meta.env_keys),
            }
        )
    return providers


def upsert_user_key(
    session: Session,
    user: User,
    provider: str,
    api_key: str | None,
    *,
    model: str | None = None,
) -> UserLlmKey:
    provider = provider.strip().lower()
    if provider not in BYOK_PROVIDERS:
        raise APIError(400, f"BYOK not supported for provider '{provider}'", "INVALID_PROVIDER")

    row = session.scalar(
        select(UserLlmKey).where(
            UserLlmKey.user_id == user.id,
            UserLlmKey.provider == provider,
        )
    )
    cleaned_key = (api_key or "").strip()
    if row is None and not cleaned_key:
        raise APIError(400, "API key is required", "VALIDATION_ERROR")

    allowed_ids = {m["id"] for m in catalog_models_for(provider)}
    chosen_model = (model or "").strip() or None
    if chosen_model and allowed_ids and chosen_model not in allowed_ids:
        # Allow custom ids for azure/local flexibility, but prefer catalog.
        if provider not in {"local", "azure"}:
            raise APIError(400, f"Unknown model '{chosen_model}' for {provider}", "INVALID_MODEL")
    if not chosen_model:
        chosen_model = default_model_for(provider)
    chosen_model = resolve_model_id(provider, chosen_model)

    now = datetime.now(timezone.utc)
    if row is None:
        row = UserLlmKey(
            user_id=user.id,
            provider=provider,
            ciphertext=encrypt_secret(cleaned_key),
            key_hint=key_hint(cleaned_key),
            model=chosen_model,
            updated_at=now,
        )
        session.add(row)
    else:
        if cleaned_key:
            row.ciphertext = encrypt_secret(cleaned_key)
            row.key_hint = key_hint(cleaned_key)
        row.model = chosen_model
        row.updated_at = now
    session.flush()
    return row


def delete_user_key(session: Session, user: User, provider: str) -> None:
    provider = provider.strip().lower()
    row = session.scalar(
        select(UserLlmKey).where(
            UserLlmKey.user_id == user.id,
            UserLlmKey.provider == provider,
        )
    )
    if row is None:
        raise APIError(404, "No stored key for this provider", "NOT_FOUND")
    session.delete(row)
    session.flush()


def get_decrypted_key(session: Session, user_id: uuid.UUID, provider: str) -> str | None:
    row = session.scalar(
        select(UserLlmKey).where(
            UserLlmKey.user_id == user_id,
            UserLlmKey.provider == provider,
        )
    )
    if row is None or not isinstance(getattr(row, "ciphertext", None), str):
        return None
    try:
        return decrypt_secret(row.ciphertext)
    except Exception:
        return None


def get_byok_model(session: Session, user_id: uuid.UUID, provider: str) -> str | None:
    row = session.scalar(
        select(UserLlmKey).where(
            UserLlmKey.user_id == user_id,
            UserLlmKey.provider == provider,
        )
    )
    if row is None or not hasattr(row, "model"):
        return None
    model = getattr(row, "model", None)
    if model is not None and not isinstance(model, str):
        return resolve_model_id(provider, None)
    return resolve_model_id(provider, model)


def user_has_any_byok(session: Session, user_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(UserLlmKey.id).where(UserLlmKey.user_id == user_id).limit(1)
        )
        is not None
    )
