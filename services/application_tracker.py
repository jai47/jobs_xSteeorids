"""Application tracker business logic."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import Application, Job, ScoredOpportunity, User
from services.application_analytics import invalidate_user_analytics_cache
from services.stage_events import append_stage_event

VALID_STATUSES = {
    "approved",
    "applied",
    "interviewing",
    "offer",
    "accepted",
    "rejected",
}

VALID_SUB_STATUSES = frozenset({"phone_screen", "technical", "onsite_loop", "final_round"})

_UNSET = object()


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
    sub_status: str | None | object = _UNSET,
    notes: str | None = None,
    applied_at: datetime | None = None,
    follow_up_due: date | None = None,
    followed_up_at: datetime | None = None,
    second_follow_up_due: date | None = None,
) -> tuple[Application, Job]:
    """Update application status, substage, or notes."""
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")

    from_status = application.status
    from_sub = application.sub_status
    status_changed = False
    sub_changed = False

    if status is not None:
        if status not in VALID_STATUSES:
            raise APIError(422, f"Invalid status: {status}", "VALIDATION_ERROR")
        if application.status != status:
            status_changed = True
        application.status = status
        if status == "applied" and application.applied_at is None:
            application.applied_at = datetime.now(timezone.utc)
        if status != "interviewing" and application.sub_status is not None:
            application.sub_status = None
            sub_changed = True
        if status in {"rejected", "accepted", "offer"}:
            from services.notifications.producers import cancel_follow_up_for_application

            cancel_follow_up_for_application(session, application.id)

    effective_status = application.status or "approved"

    if sub_status is not _UNSET:
        if sub_status is not None and effective_status != "interviewing":
            raise APIError(
                422,
                "sub_status is only valid when status is interviewing",
                "VALIDATION_ERROR",
            )
        if sub_status is not None and sub_status not in VALID_SUB_STATUSES:
            raise APIError(422, f"Invalid sub_status: {sub_status}", "VALIDATION_ERROR")
        if application.sub_status != sub_status:
            sub_changed = True
        application.sub_status = sub_status

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

    if status_changed or sub_changed:
        append_stage_event(
            session,
            application.id,
            from_status=from_status if status_changed else None,
            to_status=application.status if status_changed else None,
            from_sub=from_sub if sub_changed else None,
            to_sub=application.sub_status if sub_changed else None,
        )

    application.updated_at = datetime.now(timezone.utc)
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")

    session.flush()

    if status_changed or applied_at is not None:
        invalidate_user_analytics_cache(user.id)

    # Lazy-prep interview pack when moving into interviewing (fail-soft, sync light).
    if status_changed and application.status == "interviewing":
        try:
            from services.autopilot.interview_pack import generate_and_store_interview_pack

            generate_and_store_interview_pack(session, user, application.id, check_limits=False)
        except Exception:
            pass

    return application, job


def delete_application(
    session: Session,
    user: User,
    application_id: uuid.UUID,
) -> None:
    """Remove an application from the tracker (related cover letter/themes cascade)."""
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")

    from services.notifications.producers import cancel_follow_up_for_application

    cancel_follow_up_for_application(session, application.id)
    session.delete(application)
    session.flush()
    invalidate_user_analytics_cache(user.id)
