"""Pydantic schemas for user profile and auth."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class SetupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)


class AuthStatusResponse(BaseModel):
    has_users: bool


class LoginResponse(BaseModel):
    token: str
    user_id: str
    name: str
    email: str
    is_admin: bool = False
    token_balance: int = 1000


class UserProfileResponse(BaseModel):
    id: str
    name: str
    email: str
    nationality: str | None = None
    preferred_countries: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)
    prefers_remote: bool = False
    salary_range_min: int | None = None
    salary_range_max: int | None = None
    salary_currency: str = "USD"
    years_experience: int | None = None
    parsed_skills: list[str] = Field(default_factory=list)
    has_active_resume: bool = False
    score_warning_threshold: int = 40
    cover_letter_angles: dict[str, str] = Field(default_factory=dict)
    notify_digest_email: bool = True
    notify_followup_email: bool = True
    is_admin: bool = False
    token_balance: int = 1000
    preferred_llm_provider: str | None = None


class UserProfileUpdate(BaseModel):
    nationality: str | None = None
    preferred_countries: list[str] | None = None
    preferred_roles: list[str] | None = None
    prefers_remote: bool | None = None
    salary_range_min: int | None = None
    salary_range_max: int | None = None
    salary_currency: str | None = None
    years_experience: int | None = None
    score_warning_threshold: int | None = Field(default=None, ge=0, le=100)
    cover_letter_angles: dict[str, str] | None = None
    notify_digest_email: bool | None = None
    notify_followup_email: bool | None = None


class LLMProviderInfo(BaseModel):
    id: str
    label: str
    configured: bool
    model: str | None = None
    env_keys: list[str] = Field(default_factory=list)


class LLMStatusResponse(BaseModel):
    selected_provider: str
    providers: list[LLMProviderInfo]
    anthropic_configured: bool
    openai_configured: bool
    opencode_configured: bool
    opencode_model: str | None = None
    local_llm_configured: bool
    local_llm_model: str | None = None
    groq_configured: bool = False
    groq_model: str | None = None
    deepseek_configured: bool = False
    deepseek_model: str | None = None
    google_configured: bool = False
    google_model: str | None = None
    kimi_configured: bool = False
    kimi_model: str | None = None
    azure_configured: bool = False
    azure_deployment: str | None = None
    aws_configured: bool = False
    aws_model: str | None = None
    resume_parser_mode: str


class LLMProviderUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=32)


class ResumeTextUpload(BaseModel):
    text: str = Field(min_length=1)


class ResumeUploadResponse(BaseModel):
    master_resume_id: str
    filename: str
    skills: list[str]
    experience_years: int | None
    previous_titles: list[str]
    education: list[str]
    languages: list[str]


class BlacklistResponse(BaseModel):
    blacklisted_companies: list[str] = Field(default_factory=list)
    blacklisted_roles: list[str] = Field(default_factory=list)
    blacklisted_locations: list[str] = Field(default_factory=list)


class BlacklistUpdate(BaseModel):
    blacklisted_companies: list[str] | None = None
    blacklisted_roles: list[str] | None = None
    blacklisted_locations: list[str] | None = None
