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


class UserProfileUpdate(BaseModel):
    nationality: str | None = None
    preferred_countries: list[str] | None = None
    preferred_roles: list[str] | None = None
    prefers_remote: bool | None = None
    salary_range_min: int | None = None
    salary_range_max: int | None = None
    salary_currency: str | None = None
    years_experience: int | None = None


class LLMStatusResponse(BaseModel):
    anthropic_configured: bool
    openai_configured: bool
    opencode_configured: bool
    opencode_model: str | None = None
    local_llm_configured: bool
    local_llm_model: str | None = None
    resume_parser_mode: str


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
