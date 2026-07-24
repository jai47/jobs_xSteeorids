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
        "DeepSeek V3",
        ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"),
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
) -> str:
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


def _call_azure(
    prompt: str,
    purpose: str,
    user_id: uuid.UUID,
    session: Session,
    max_tokens: int,
) -> str:
    client = openai.AzureOpenAI(
        api_key=settings.azure_openai_api_key,
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


def is_provider_configured(provider_id: str) -> bool:
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
) -> str:
    if provider_id == "groq":
        return _call_openai_compatible(
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
            model=settings.groq_model,
            provider="groq",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "anthropic":
        return _call_anthropic(prompt, purpose, user_id, session, max_tokens)
    if provider_id == "deepseek":
        return _call_openai_compatible(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            provider="deepseek",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "google":
        return _call_openai_compatible(
            api_key=settings.google_ai_api_key,
            base_url=settings.google_ai_base_url,
            model=settings.google_ai_model,
            provider="google",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "kimi":
        return _call_openai_compatible(
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_base_url,
            model=settings.kimi_model,
            provider="kimi",
            prompt=prompt,
            purpose=purpose,
            user_id=user_id,
            session=session,
            max_tokens=max_tokens,
        )
    if provider_id == "azure":
        return _call_azure(prompt, purpose, user_id, session, max_tokens)
    if provider_id == "aws":
        return _call_bedrock(prompt, purpose, user_id, session, max_tokens)
    if provider_id == "opencode":
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
    if provider_id == "local":
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
    if provider_id == "openai":
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
    raise ValueError(f"Unknown provider: {provider_id}")


def provider_label(provider_id: str) -> str:
    return PROVIDER_META.get(provider_id, ProviderMeta(provider_id, provider_id, ())).label


def provider_error_label(provider_id: str) -> str:
    return provider_label(provider_id)


def resolve_provider_chain() -> list[str]:
    """Build ordered provider list: preferred first, then default chain."""
    selected = get_selected_provider()
    if selected == "auto":
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
