"""Pydantic schemas for application tracker."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ApplicationResponse(BaseModel):
    id: str
    job_id: str
    company: str
    title: str
    country: str | None = None
    status: str
    sub_status: str | None = None
    time_in_stage_days: int | None = None
    applied_at: datetime | None = None
    follow_up_due: date | None = None
    followed_up_at: datetime | None = None
    second_follow_up_due: date | None = None
    notes: str | None = None
    updated_at: datetime | None = None
    opportunity_id: str | None = None
    resume_version_id: str | None = None
    is_follow_up_overdue: bool = False
    is_second_follow_up_overdue: bool = False
    cover_letter_status: str | None = None
    overall_score: float | None = None
    score_skill_match: float | None = None
    score_role_match: float | None = None
    score_experience: float | None = None
    score_country_pref: float | None = None
    score_remote_pref: float | None = None
    score_fit: float | None = None
    score_visa: int | None = None


class ApplicationListResponse(BaseModel):
    applications: list[ApplicationResponse]


class ApplicationUpdate(BaseModel):
    status: str | None = None
    sub_status: str | None = None
    notes: str | None = None
    applied_at: datetime | None = None
    follow_up_due: date | None = None
    followed_up_at: datetime | None = None
    second_follow_up_due: date | None = None
