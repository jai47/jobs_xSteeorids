"""Pydantic schemas for F05 application analytics."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsBucket(BaseModel):
    key: str
    applications: int
    responses: int
    rate: float


class DaysToResponse(BaseModel):
    p50: int | None = None
    p90: int | None = None
    sample_size: int = 0


class ApplicationAnalyticsUnlocked(BaseModel):
    unlocked: bool = True
    qualifying_applications: int
    response_rate_overall: float
    by_country: list[AnalyticsBucket] = Field(default_factory=list)
    by_archetype: list[AnalyticsBucket] = Field(default_factory=list)
    by_score_band: list[AnalyticsBucket] = Field(default_factory=list)
    days_to_first_response: DaysToResponse
    excluded_pre_event_log: int = 0


class ApplicationAnalyticsLocked(BaseModel):
    unlocked: bool = False
    qualifying_applications: int
    required: int = 10
