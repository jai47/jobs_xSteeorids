"""Read skill gap reports for the dashboard."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.models import SkillGapReport, User


def _serialize_report(report: SkillGapReport | None) -> dict[str, Any] | None:
    """Convert a SkillGapReport row to an API payload."""
    if report is None:
        return None
    return {
        "period_type": report.period_type,
        "period_start": report.period_start.isoformat() if report.period_start else None,
        "period_end": report.period_end.isoformat() if report.period_end else None,
        "top_missing_skills": list(report.top_missing_skills or []),
        "total_jobs_analysed": report.total_jobs_analysed,
    }


def get_skill_gap_reports(session: Session, user: User) -> dict[str, Any]:
    """Return the latest weekly and monthly skill gap reports for a user."""
    weekly = (
        session.query(SkillGapReport)
        .filter_by(user_id=user.id, period_type="weekly")
        .order_by(SkillGapReport.period_end.desc(), SkillGapReport.created_at.desc())
        .first()
    )
    monthly = (
        session.query(SkillGapReport)
        .filter_by(user_id=user.id, period_type="monthly")
        .order_by(SkillGapReport.period_end.desc(), SkillGapReport.created_at.desc())
        .first()
    )
    return {
        "weekly": _serialize_report(weekly),
        "monthly": _serialize_report(monthly),
    }
