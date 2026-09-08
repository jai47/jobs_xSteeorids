"""LLM provider registry — configuration checks and call implementations."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import anthropic
import openai
from sqlalchemy.orm import Session

from config import settings
from db.models import LLMUsage
from services.llm_runtime_config import get_selected_provider

log = logging.getLogger(__name__)

ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
OPENAI_MODEL = "gpt-4o"

DEFAULT_CHAIN = (
    "groq",
    "anthropic",
    "deepseek",
    "google",
    "kimi",
    "azure",
    "aws",
    "opencode",
    "local",
    "openai",
)


@dataclass(frozen=True)
class ProviderMeta:
    id: str
    label: str
    env_keys: tuple[str, ...]


PROVIDER_META: dict[str, ProviderMeta] = {
    "auto": ProviderMeta("auto", "Auto (fallback chain)", ()),
    "groq": ProviderMeta("groq", "Groq", ("GROQ_API_KEY", "GROQ_MODEL")),
    "anthropic": ProviderMeta("anthropic", "Anthropic Claude", ("ANTHROPIC_API_KEY",)),
    "deepseek": ProviderMeta(
        "deepseek",
        "DeepSeek",
        ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"),
    ),
    "google": ProviderMeta(
        "google",
        "Google AI Studio (Gemini)",
        ("GOOGLE_AI_API_KEY", "GOOGLE_AI_MODEL"),
    ),
    "kimi": ProviderMeta("kimi", "Kimi (Moonshot)", ("KIMI_API_KEY", "KIMI_MODEL")),
    "azure": ProviderMeta(
        "azure",
        "Azure OpenAI",
        (
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_DEPLOYMENT",
        ),
    ),
    "aws": ProviderMeta(
        "aws",
        "AWS Bedrock",
        ("AWS_REGION", "AWS_BEDROCK_MODEL_ID"),
    ),
    "opencode": ProviderMeta(
        "opencode",
        "OpenCode Zen",
        ("OPENCODE_API_KEY", "OPENCODE_MODEL"),
    ),
    "local": ProviderMeta(
        "local",
        "Local Ollama",
        ("LOCAL_LLM_BASE_URL", "LOCAL_LLM_MODEL"),
    ),
    "openai": ProviderMeta("openai", "OpenAI", ("OPENAI_API_KEY",)),
}

# Models users can pick for BYOK (ids must be valid for that provider's API).
PROVIDER_MODEL_CATALOG: dict[str, list[dict[str, str]]] = {
    "groq": [
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B (recommended)"},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B"},
        {"id": "qwen/qwen3.6-27b", "label": "Qwen 3.6 27B"},
        {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "label": "Llama 4 Scout 17B"},
    ],
    "anthropic": [
        {"id": ANTHROPIC_MODEL, "label": "Claude Sonnet 4"},
        {"id": "claude-3-5-haiku-20241022", "label": "Claude 3.5 Haiku"},
    ],
    "deepseek": [
        {"id": "deepseek-chat", "label": "DeepSeek Chat"},
        {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner"},
    ],
    "google": [
        {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        {"id": "gemini-1.5-pro", "label": "Gemini 1.5 Pro"},
    ],
    "kimi": [
        {"id": "kimi-k2-0905-preview", "label": "Kimi K2"},
        {"id": "moonshot-v1-128k", "label": "Moonshot v1 128k"},
    ],
    "openai": [
        {"id": "gpt-4o", "label": "GPT-4o"},
        {"id": "gpt-4o-mini", "label": "GPT-4o mini"},
        {"id": "gpt-4.1", "label": "GPT-4.1"},
        {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini"},
    ],
    "opencode": [
        {"id": "mimo-v2.5-free", "label": "MiMo v2.5 free"},
    ],
    "local": [
        {"id": "llama3.2", "label": "llama3.2"},
        {"id": "llama3.1", "label": "llama3.1"},
        {"id": "mistral", "label": "mistral"},
    ],
    "azure": [],
    "aws": [],
}


def catalog_models_for(provider_id: str) -> list[dict[str, str]]:
    return list(PROVIDER_MODEL_CATALOG.get(provider_id, []))


def default_model_for(provider_id: str) -> str | None:
    models = catalog_models_for(provider_id)
    if models:
        return models[0]["id"]
    return provider_model_name(provider_id)


def resolve_model_id(provider_id: str, model_override: str | None = None) -> str:
    """Pick model: explicit override → catalog default → settings."""
    cleaned = (model_override or "").strip()
    if cleaned:
        # Reject known-dead Groq Llama id so BYOK keeps working.
        if provider_id == "groq" and cleaned == "llama-3.3-70b-versatile":
            return default_model_for("groq") or settings.groq_model
        return cleaned
    fallback = default_model_for(provider_id)
    if fallback:
        return fallback
    name = provider_model_name(provider_id)
    if name:
        return name
    raise ValueError(f"No model configured for provider {provider_id}")


def _log_usage(
    session: Session,
    user_id: uuid.UUID,
    provider: str,
    model: str,
    purpose: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
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


def _call_anthropic(
    prompt: str,
    purpose: str,
    user_id: uuid.UUID,
    session: Session,
    max_tokens: int,
    *,
    api_key_override: str | None = None,
    model_override: str | None = None,
) -> str:
    model = resolve_model_id("anthropic", model_override)
    client = anthropic.Anthropic(api_key=api_key_override or settings.anthropic_api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    _log_usage(
        session,
        user_id,
        "anthropic",
        model,
        purpose,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return text


def _call_azure(
    prompt: str,
    purpose: str,
    user_id: uuid.UUID,
    session: Session,
    max_tokens: int,
    *,
    api_key_override: str | None = None,
) -> str:
    client = openai.AzureOpenAI(
        api_key=api_key_override or settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        azure_endpoint=settings.azure_openai_endpoint,
    )
    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content or ""
    usage = response.usage
    _log_usage(
        session,
        user_id,
        "azure",
        settings.azure_openai_deployment,
        purpose,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )
    return text


def _call_bedrock(
    prompt: str,
    purpose: str,
    user_id: uuid.UUID,
    session: Session,
    max_tokens: int,
) -> str:
    import boto3

    client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    response = client.converse(
        modelId=settings.aws_bedrock_model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )
    content = response.get("output", {}).get("message", {}).get("content", [])
    text = content[0].get("text", "") if content else ""
    usage = response.get("usage", {})
    _log_usage(
        session,
        user_id,
        "aws",
        settings.aws_bedrock_model_id,
        purpose,
        int(usage.get("inputTokens", 0)),
        int(usage.get("outputTokens", 0)),
    )
    return text


def is_provider_configured(
    provider_id: str,
    *,
    user_api_key: str | None = None,
) -> bool:
    if user_api_key:
        if provider_id == "azure":
            return bool(
                user_api_key
                and settings.azure_openai_endpoint
                and settings.azure_openai_deployment
            )
        if provider_id in {
            "groq",
            "anthropic",
            "deepseek",
            "google",
            "kimi",
            "opencode",
            "openai",
            "local",
        }:
            return True
    if provider_id == "auto":
        return any(is_provider_configured(pid) for pid in DEFAULT_CHAIN)
    if provider_id == "groq":
        return bool(settings.groq_api_key)
    if provider_id == "anthropic":
        return bool(settings.anthropic_api_key)
    if provider_id == "deepseek":
        return bool(settings.deepseek_api_key)
    if provider_id == "google":
        return bool(settings.google_ai_api_key)
    if provider_id == "kimi":
        return bool(settings.kimi_api_key)
    if provider_id == "azure":
        return bool(
            settings.azure_openai_api_key
            and settings.azure_openai_endpoint
            and settings.azure_openai_deployment
        )
    if provider_id == "aws":
        return bool(settings.aws_region and settings.aws_bedrock_model_id)
    if provider_id == "opencode":
        return bool(settings.opencode_api_key)
    if provider_id == "local":
        return bool(settings.local_llm_base_url)
    if provider_id == "openai":
        return bool(settings.openai_api_key)
    return False


def provider_model_name(provider_id: str) -> str | None:
    if not is_provider_configured(provider_id):
        return None
    models = {
        "groq": settings.groq_model,
        "anthropic": ANTHROPIC_MODEL,
        "deepseek": settings.deepseek_model,
        "google": settings.google_ai_model,
        "kimi": settings.kimi_model,
        "azure": settings.azure_openai_deployment,
        "aws": settings.aws_bedrock_model_id,
        "opencode": settings.opencode_model,
        "local": settings.local_llm_model,
        "openai": OPENAI_MODEL,
    }
    return models.get(provider_id)


def call_provider(
    provider_id: str,
    prompt: str,
    purpose: str,
    user_id: uuid.UUID,
    session: Session,
    max_tokens: int,
    *,
    api_key_override: str | None = None,
    model_override: str | None = None,
) -> str:
    model = resolve_model_id(provider_id, model_override)
    if provider_id == "groq":
        return _call_openai_compatible(
            api_key=api_key_override or settings.groq_api_key,
            base_url=settings.groq_base_url,
            model=model,
            provider="groq",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "anthropic":
        return _call_anthropic(
            prompt,
            purpose,
            user_id,
            session,
            max_tokens,
            api_key_override=api_key_override,
            model_override=model,
        )
    if provider_id == "deepseek":
        return _call_openai_compatible(
            api_key=api_key_override or settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=model,
            provider="deepseek",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "google":
        return _call_openai_compatible(
            api_key=api_key_override or settings.google_ai_api_key,
            base_url=settings.google_ai_base_url,
            model=model,
            provider="google",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "kimi":
        return _call_openai_compatible(
            api_key=api_key_override or settings.kimi_api_key,
            base_url=settings.kimi_base_url,
            model=model,
            provider="kimi",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "azure":
        return _call_azure(
            prompt,
            purpose,
            user_id,
            session,
            max_tokens,
            api_key_override=api_key_override,
        )
    if provider_id == "aws":
        return _call_bedrock(prompt, purpose, user_id, session, max_tokens)
    if provider_id == "opencode":
        return _call_openai_compatible(
            api_key=api_key_override or settings.opencode_api_key,
            base_url=settings.opencode_base_url,
            model=model,
            provider="opencode",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "local":
        return _call_openai_compatible(
            api_key=api_key_override or settings.local_llm_api_key or "ollama",
            base_url=settings.local_llm_base_url,
            model=model,
            provider="local",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "openai":
        return _call_openai_compatible(
            api_key=api_key_override or settings.openai_api_key,
            base_url=None,
            model=model,
            provider="openai",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    raise ValueError(f"Unknown provider: {provider_id}")


def provider_label(provider_id: str) -> str:
    return PROVIDER_META.get(provider_id, ProviderMeta(provider_id, provider_id, ())).label


def provider_error_label(provider_id: str) -> str:
    return provider_label(provider_id)


def resolve_provider_chain(preferred: str | None = None) -> list[str]:
    """Build ordered provider list: preferred first, then default chain."""
    selected = (preferred or get_selected_provider() or "auto").strip().lower()
    if selected in {"", "auto"}:
        return list(DEFAULT_CHAIN)
    rest = [pid for pid in DEFAULT_CHAIN if pid != selected]
    return [selected, *rest]


def build_status_payload() -> dict[str, Any]:
    """Shape data for LLMStatusResponse."""
    providers = []
    for pid in ("auto", *DEFAULT_CHAIN):
        meta = PROVIDER_META[pid]
        providers.append(
            {
                "id": pid,
                "label": meta.label,
                "configured": is_provider_configured(pid),
                "model": provider_model_name(pid) if pid != "auto" else None,
                "env_keys": list(meta.env_keys),
            }
        )
    return {
        "selected_provider": get_selected_provider(),
        "providers": providers,
        "anthropic_configured": is_provider_configured("anthropic"),
        "openai_configured": is_provider_configured("openai"),
        "opencode_configured": is_provider_configured("opencode"),
        "opencode_model": provider_model_name("opencode"),
        "local_llm_configured": is_provider_configured("local"),
        "local_llm_model": provider_model_name("local"),
        "groq_configured": is_provider_configured("groq"),
        "groq_model": provider_model_name("groq"),
        "deepseek_configured": is_provider_configured("deepseek"),
        "deepseek_model": provider_model_name("deepseek"),
        "google_configured": is_provider_configured("google"),
        "google_model": provider_model_name("google"),
        "kimi_configured": is_provider_configured("kimi"),
        "kimi_model": provider_model_name("kimi"),
        "azure_configured": is_provider_configured("azure"),
        "azure_deployment": provider_model_name("azure"),
        "aws_configured": is_provider_configured("aws"),
        "aws_model": provider_model_name("aws"),
        "resume_parser_mode": settings.resume_parser_mode,
    }
