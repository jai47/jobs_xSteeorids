"""Notification outbox producers with dedupe keys."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db.models import Application, DailyDigest, Notification, PipelineRun, User
from pipeline.stages.overall_scorer import DIGEST_MIN_SCORE
from services.application_tracker import _follow_up_flags

log = logging.getLogger(__name__)


def _enqueue(
    session: Session,
    *,
    user_id: uuid.UUID,
    type_: str,
    channel: str,
    payload: dict[str, Any],
    dedupe_key: str,
    scheduled_for: datetime | None = None,
) -> bool:
    """Insert notification if dedupe_key is new. Returns True if inserted."""
    now = datetime.now(timezone.utc)
    status = "sent" if channel == "in_app" else "pending"
    stmt = (
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            type=type_,
            channel=channel,
            payload_json=payload,
            dedupe_key=dedupe_key,
            status=status,
            attempts=0,
            scheduled_for=scheduled_for or now,
            sent_at=now if channel == "in_app" else None,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    result = session.execute(stmt)
    session.flush()
    return result.rowcount > 0


def count_overdue_follow_ups(session: Session, user: User) -> int:
    applications = session.query(Application).filter_by(user_id=user.id).all()
    count = 0
    for app in applications:
        first, second = _follow_up_flags(app)
        if first or second:
            count += 1
    return count


def enqueue_digest_notifications(
    session: Session,
    user: User,
    digest_date: date,
    digest: DailyDigest,
    *,
    digest_eligible_count: int,
    overdue_follow_ups: int,
) -> None:
    """Enqueue in-app + optional email digest notifications (no empty emails)."""
    if digest_eligible_count < 1 and overdue_follow_ups < 1:
        return

    payload = {
        "title": f"Daily digest — {digest_date.isoformat()}",
        "body": f"{digest_eligible_count} opportunities scored ≥{int(DIGEST_MIN_SCORE)}.",
        "link_path": "/digest",
        "digest_date": digest_date.isoformat(),
        "content_preview": (digest.content_text or "")[:500],
    }
    dedupe_in_app = f"digest:{user.id}:{digest_date.isoformat()}:in_app"
    _enqueue(
        session,
        user_id=user.id,
        type_="digest_email",
        channel="in_app",
        payload=payload,
        dedupe_key=dedupe_in_app,
    )

    if not user.notify_digest_email:
        return

    email_payload = {
        **payload,
        "subject": f"AI Career Digest — {digest_date.isoformat()}",
        "content_text": digest.content_text,
        "user_name": user.name,
    }
    dedupe_email = f"digest:{user.id}:{digest_date.isoformat()}:email"
    _enqueue(
        session,
        user_id=user.id,
        type_="digest_email",
        channel="email",
        payload=email_payload,
        dedupe_key=dedupe_email,
    )


def enqueue_cover_letter_ready(
    session: Session,
    user: User,
    application: Application,
    job_company: str,
    job_title: str,
) -> None:
    payload = {
        "title": "Cover letter ready",
        "body": f"Draft cover letter for {job_company} — {job_title}",
        "link_path": f"/tracker?application={application.id}",
        "application_id": str(application.id),
    }
    dedupe = f"cover_letter_ready:{application.id}"
    _enqueue(
        session,
        user_id=user.id,
        type_="cover_letter_ready",
        channel="in_app",
        payload=payload,
        dedupe_key=dedupe,
    )


def enqueue_follow_up_in_app(
    session: Session,
    user: User,
    application: Application,
    job_company: str,
    job_title: str,
    *,
    reminder_type: str,
    days_since: int,
) -> None:
    label = "7 days" if reminder_type == "7d" else "14 days"
    payload = {
        "title": f"Follow up with {job_company}",
        "body": f"{job_title} — applied {days_since} days ago ({label} reminder)",
        "link_path": f"/tracker?application={application.id}",
        "application_id": str(application.id),
        "reminder_type": reminder_type,
    }
    dedupe = f"follow_up:{application.id}:{reminder_type}:in_app"
    _enqueue(
        session,
        user_id=user.id,
        type_="follow_up",
        channel="in_app",
        payload=payload,
        dedupe_key=dedupe,
    )


def enqueue_follow_up_email_batch(
    session: Session,
    user: User,
    items: list[dict[str, Any]],
    batch_date: date,
) -> None:
    if not user.notify_followup_email or not items:
        return
    payload = {
        "title": f"Follow-up reminders ({len(items)})",
        "body": f"You have {len(items)} application(s) needing follow-up.",
        "link_path": "/tracker",
        "items": items,
        "user_name": user.name,
    }
    dedupe = f"follow_up_email:{user.id}:{batch_date.isoformat()}"
    _enqueue(
        session,
        user_id=user.id,
        type_="follow_up",
        channel="email",
        payload=payload,
        dedupe_key=dedupe,
    )


def cancel_follow_up_for_application(session: Session, application_id: uuid.UUID) -> int:
    """Cancel pending follow-up notifications for an application."""
    prefix = f"follow_up:{application_id}:"
    rows = (
        session.query(Notification)
        .filter(
            Notification.type == "follow_up",
            Notification.status.in_(("pending", "sent")),
            Notification.dedupe_key.like(f"{prefix}%"),
        )
        .all()
    )
    now = datetime.now(timezone.utc)
    for row in rows:
        row.status = "cancelled"
        row.sent_at = now
    session.flush()
    return len(rows)


def enqueue_pipeline_status_notification(
    session: Session,
    user: User,
    run: PipelineRun,
) -> bool:
    """In-app alert for failed/partial pipeline runs (replaces HealthBanner)."""
    if run.status == "failed":
        err = (run.error_message or "").strip()
        title = "Pipeline run failed"
        body = f"Last pipeline run failed{f': {err}' if err else ''}"
    elif run.status == "partial":
        title = "Pipeline completed with errors"
        body = "Last pipeline run completed with partial errors — check Pipeline."
    else:
        return False

    return _enqueue(
        session,
        user_id=user.id,
        type_="pipeline_status",
        channel="in_app",
        payload={
            "title": title,
            "body": body,
            "link_path": "/status",
            "pipeline_run_id": str(run.id),
            "status": run.status,
        },
        dedupe_key=f"pipeline:{run.id}:{run.status}",
    )


def ensure_pipeline_health_notifications(session: Session, user: User) -> None:
    """Backfill bell items for the latest run (and a once-per-day idle reminder)."""
    run = (
        session.query(PipelineRun)
        .filter(PipelineRun.user_id == user.id)
        .order_by(PipelineRun.run_date.desc())
        .first()
    )
    if run is None:
        return

    if run.status in ("failed", "partial"):
        enqueue_pipeline_status_notification(session, user, run)
        return

    today = date.today()
    if run.status == "running" or run.run_date == today:
        return

    _enqueue(
        session,
        user_id=user.id,
        type_="pipeline_status",
        channel="in_app",
        payload={
            "title": "Pipeline not run today",
            "body": "Pipeline has not run today. Refresh opportunities from Pipeline.",
            "link_path": "/status",
            "pipeline_run_id": str(run.id),
            "status": "idle",
        },
        dedupe_key=f"pipeline:idle:{user.id}:{today.isoformat()}",
    )
