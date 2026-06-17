"""Skill gap report routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from db.models import User
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
