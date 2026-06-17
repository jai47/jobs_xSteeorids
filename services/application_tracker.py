"""Application tracker business logic."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import Application, Job, ScoredOpportunity, User

VALID_STATUSES = {
    "approved",
    "applied",
    "interviewing",
    "offer",
    "accepted",
    "rejected",
}


def _follow_up_flags(application: Application) -> tuple[bool, bool]:
    """Return (7d overdue, 14d overdue) flags for an application."""
    today = date.today()
    first_overdue = bool(
        application.follow_up_due
        and application.follow_up_due <= today
        and application.followed_up_at is None
    )
    second_overdue = bool(
        application.second_follow_up_due
        and application.second_follow_up_due <= today
    )
    return first_overdue, second_overdue


def list_applications(session: Session, user: User) -> list[tuple[Application, Job, ScoredOpportunity | None]]:
    """Return all applications for a user with job details."""
    rows = (
        session.query(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .filter(Application.user_id == user.id)
        .order_by(Application.updated_at.desc())
        .all()
    )
    result: list[tuple[Application, Job, ScoredOpportunity | None]] = []
    for application, job in rows:
        opp = (
            session.query(ScoredOpportunity)
            .filter_by(job_id=job.id, user_id=user.id)
            .order_by(ScoredOpportunity.created_at.desc())
            .first()
        )
        result.append((application, job, opp))
    return result


def update_application(
    session: Session,
    user: User,
    application_id: uuid.UUID,
    *,
    status: str | None = None,
    notes: str | None = None,
    applied_at: datetime | None = None,
    follow_up_due: date | None = None,
    followed_up_at: datetime | None = None,
    second_follow_up_due: date | None = None,
) -> tuple[Application, Job]:
    """Update application status or notes."""
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")

    if status is not None:
        if status not in VALID_STATUSES:
            raise APIError(422, f"Invalid status: {status}", "VALIDATION_ERROR")
        application.status = status
        if status == "applied" and application.applied_at is None:
            application.applied_at = datetime.now(timezone.utc)

    if notes is not None:
        application.notes = notes
    if applied_at is not None:
        application.applied_at = applied_at
    if follow_up_due is not None:
        application.follow_up_due = follow_up_due
    if followed_up_at is not None:
        application.followed_up_at = followed_up_at
    if second_follow_up_due is not None:
        application.second_follow_up_due = second_follow_up_due

    application.updated_at = datetime.now(timezone.utc)
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")

    session.flush()
    return application, job
