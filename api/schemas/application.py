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
    applied_at: datetime | None = None
    follow_up_due: date | None = None
    followed_up_at: datetime | None = None
    second_follow_up_due: date | None = None
    notes: str | None = None
    updated_at: datetime | None = None
    opportunity_id: str | None = None
    is_follow_up_overdue: bool = False
    is_second_follow_up_overdue: bool = False


class ApplicationListResponse(BaseModel):
    applications: list[ApplicationResponse]


class ApplicationUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    applied_at: datetime | None = None
    follow_up_due: date | None = None
    followed_up_at: datetime | None = None
    second_follow_up_due: date | None = None
