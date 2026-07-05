"""Skill gap and application analytics report routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Union

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.analytics import (
    ApplicationAnalyticsLocked,
    ApplicationAnalyticsUnlocked,
)
from db.models import User
from services.application_analytics import get_application_analytics_cached
from services.skill_gap_reports import get_skill_gap_reports as fetch_skill_gap_reports

router = APIRouter(prefix="/reports", tags=["reports"])


class SkillGapPeriod(BaseModel):
    period_type: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    top_missing_skills: list[dict[str, Any]] | None = None
    total_jobs_analysed: int | None = None


class SkillGapReportResponse(BaseModel):
    weekly: SkillGapPeriod | None = None
    monthly: SkillGapPeriod | None = None


@router.get("/skill-gap", response_model=SkillGapReportResponse)
def get_skill_gap_reports(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SkillGapReportResponse:
    """Return the latest weekly and monthly skill gap reports."""
    payload = fetch_skill_gap_reports(db, user)
    return SkillGapReportResponse(
        weekly=payload["weekly"],
        monthly=payload["monthly"],
    )


@router.get(
    "/application-analytics",
    response_model=Union[ApplicationAnalyticsUnlocked, ApplicationAnalyticsLocked],
)
def get_application_analytics(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> ApplicationAnalyticsUnlocked | ApplicationAnalyticsLocked:
    """F05 — response-rate analytics (locked below 10 qualifying applications)."""
    payload = get_application_analytics_cached(
        db, user, date_from=date_from, date_to=date_to
    )
    if not payload.get("unlocked"):
        return ApplicationAnalyticsLocked(**payload)
    return ApplicationAnalyticsUnlocked(**payload)
