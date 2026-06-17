"""
Skill gap report. Identifies skills most frequently required in jobs the user
is a strong fit for, but absent from the user's resume.
Zero LLM cost. Pure PostgreSQL query.
"""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.models import SkillGapReport, User

log = logging.getLogger(__name__)

SKILL_GAP_QUERY = """
SELECT
  unnested_skill AS skill,
  COUNT(DISTINCT j.id) AS job_count,
  ROUND(AVG(so.overall_score)::numeric, 1) AS avg_score
FROM jobs j
JOIN scored_opportunities so ON so.job_id = j.id
CROSS JOIN UNNEST(j.skills_required) AS unnested_skill
WHERE so.user_id = :user_id
  AND so.score_fit >= 50
  AND DATE(j.created_at) BETWEEN :period_start AND :period_end
  AND unnested_skill NOT IN (
    SELECT UNNEST(COALESCE(parsed_skills, ARRAY[]::varchar[]))
    FROM users
    WHERE id = :user_id
  )
GROUP BY unnested_skill
ORDER BY job_count DESC
LIMIT 20
"""

TOTAL_JOBS_QUERY = """
SELECT COUNT(DISTINCT j.id) AS total_jobs
FROM jobs j
JOIN scored_opportunities so ON so.job_id = j.id
WHERE so.user_id = :user_id
  AND so.score_fit >= 50
  AND DATE(j.created_at) BETWEEN :period_start AND :period_end
"""


def is_weekly_report_day(run_date: date) -> bool:
    """Weekly reports run on Fridays."""
    return run_date.weekday() == 4


def is_monthly_report_day(run_date: date) -> bool:
    """Monthly reports run on the last calendar day of the month."""
    return run_date.day == calendar.monthrange(run_date.year, run_date.month)[1]


def period_bounds(period_type: str, run_date: date) -> tuple[date, date]:
    """Return inclusive period_start and period_end for a report type."""
    if period_type == "weekly":
        period_end = run_date
        period_start = run_date - timedelta(days=6)
        return period_start, period_end

    if period_type == "monthly":
        period_start = run_date.replace(day=1)
        return period_start, run_date

    raise ValueError(f"Unknown period_type: {period_type}")


def query_skill_gaps(
    session: Session,
    user_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> tuple[list[dict[str, Any]], int]:
    """Run skill gap SQL and return ranked missing skills plus jobs analysed."""
    params = {
        "user_id": user_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    rows = session.execute(text(SKILL_GAP_QUERY), params).mappings().all()
    total_row = session.execute(text(TOTAL_JOBS_QUERY), params).mappings().one()
    skills = [
        {
            "skill": row["skill"],
            "job_count": int(row["job_count"]),
            "avg_score": float(row["avg_score"]) if row["avg_score"] is not None else None,
        }
        for row in rows
    ]
    return skills, int(total_row["total_jobs"] or 0)


def generate_skill_gap_report(
    session: Session,
    user: User,
    period_type: str,
    run_date: date,
) -> SkillGapReport | None:
    """Build and persist one skill gap report for a user."""
    if not user.parsed_skills:
        log.info("Skipping skill gap report for user %s: no parsed skills", user.email)
        return None

    period_start, period_end = period_bounds(period_type, run_date)
    existing = (
        session.query(SkillGapReport)
        .filter_by(
            user_id=user.id,
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
        )
        .first()
    )
    if existing is not None:
        return existing

    top_missing_skills, total_jobs = query_skill_gaps(
        session,
        user.id,
        period_start,
        period_end,
    )
    report = SkillGapReport(
        user_id=user.id,
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        top_missing_skills=top_missing_skills,
        total_jobs_analysed=total_jobs,
    )
    session.add(report)
    session.flush()
    log.info(
        "Skill gap %s report for user %s: %s jobs, %s missing skills",
        period_type,
        user.email,
        total_jobs,
        len(top_missing_skills),
    )
    return report


def maybe_generate_skill_gap_reports(
    session: Session,
    users: list[User],
    run_date: date | None = None,
) -> list[SkillGapReport]:
    """Generate weekly and/or monthly reports when the calendar triggers match."""
    today = run_date or date.today()
    period_types: list[str] = []
    if is_weekly_report_day(today):
        period_types.append("weekly")
    if is_monthly_report_day(today):
        period_types.append("monthly")
    if not period_types:
        return []

    reports: list[SkillGapReport] = []
    for user in users:
        for period_type in period_types:
            report = generate_skill_gap_report(session, user, period_type, today)
            if report is not None:
                reports.append(report)
    return reports
