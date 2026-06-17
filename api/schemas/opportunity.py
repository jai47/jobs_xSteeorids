"""Pydantic schemas for scored opportunities."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class OpportunitySummary(BaseModel):
    id: str
    job_id: str
    company: str
    title: str
    country: str | None = None
    city: str | None = None
    remote_type: str | None = None
    salary_display: str | None = None
    overall_score: float | None = None
    classification: str | None = None
    visa_status: str | None = None
    score_visa: int | None = None
    user_feedback: str | None = None
    digest_date: date | None = None
    created_at: datetime | None = None
    url: str | None = None
    is_stale: bool = False


class OpportunityDetail(OpportunitySummary):
    description: str | None = None
    fit_reasoning: str | None = None
    visa_reasoning: str | None = None
    score_skill_match: float | None = None
    score_role_match: float | None = None
    score_experience: float | None = None
    score_country_pref: float | None = None
    score_remote_pref: float | None = None
    score_fit: float | None = None
    skills_required: list[str] = Field(default_factory=list)


class OpportunityListResponse(BaseModel):
    items: list[OpportunitySummary]
    total: int
    page: int
    page_size: int


class RejectRequest(BaseModel):
    reason: str = Field(description="company | role | location | other")


class OpportunityActionResponse(BaseModel):
    id: str
    user_feedback: str
    reject_reason: str | None = None
    application_id: str | None = None
