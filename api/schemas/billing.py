"""Schemas for token billing and BYOK."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BillingRatesResponse(BaseModel):
    pipeline_run_tokens: int
    llm_call_tokens: int
    signup_grant_tokens: int
    usd_per_thousand_tokens: float = 1.0


class BillingRatesUpdate(BaseModel):
    pipeline_run_tokens: int | None = Field(default=None, ge=0)
    llm_call_tokens: int | None = Field(default=None, ge=0)
    signup_grant_tokens: int | None = Field(default=None, ge=0)
    usd_per_thousand_tokens: float | None = Field(default=None, ge=0)


class UsageDayPoint(BaseModel):
    date: str
    spent: int


class BillingUsageResponse(BaseModel):
    token_balance: int
    spent_today: int
    daily_generation_used: int
    daily_generation_limit: int
    rates: BillingRatesResponse
    series: list[UsageDayPoint] = Field(default_factory=list)
    request_tokens_hint: str = (
        "To add tokens, ask an admin to grant them from the Admin panel."
    )


class UserLlmModelOption(BaseModel):
    id: str
    label: str


class UserLlmProviderStatus(BaseModel):
    id: str
    label: str
    byok_supported: bool
    configured: bool
    key_hint: str | None = None
    model: str | None = None
    models: list[UserLlmModelOption] = Field(default_factory=list)
    env_keys: list[str] = Field(default_factory=list)


class UserLlmKeysResponse(BaseModel):
    preferred_provider: str = "auto"
    providers: list[UserLlmProviderStatus]


class UserLlmKeyUpsert(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    api_key: str | None = Field(default=None, max_length=4096)
    model: str | None = Field(default=None, max_length=128)


class UserPreferredProviderUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=32)


class AdminUserRow(BaseModel):
    id: str
    name: str
    email: str
    token_balance: int
    is_admin: bool


class AdminUserListResponse(BaseModel):
    users: list[AdminUserRow]


class GrantTokensRequest(BaseModel):
    amount: int = Field(gt=0, le=1_000_000)
    note: str | None = Field(default=None, max_length=500)


class GrantTokensResponse(BaseModel):
    user_id: str
    token_balance: int
    granted: int


class SetAdminRequest(BaseModel):
    is_admin: bool


class SetAdminResponse(BaseModel):
    user_id: str
    email: str
    is_admin: bool


class AdminByokProvider(BaseModel):
    id: str
    label: str
    configured: bool
    key_hint: str | None = None


class AdminUserDetailResponse(BaseModel):
    id: str
    name: str
    email: str
    token_balance: int
    is_admin: bool
    preferred_llm_provider: str | None = None
    byok_providers: list[AdminByokProvider] = Field(default_factory=list)
