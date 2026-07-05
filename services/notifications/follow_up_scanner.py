"""Daily follow-up scanner across all users."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from db.models import Application, Job, User
from services.application_tracker import _follow_up_flags
from services.follow_up_draft import days_since_applied, render_follow_up_draft
from services.notifications.producers import enqueue_follow_up_email_batch, enqueue_follow_up_in_app

log = logging.getLogger(__name__)


def scan_follow_ups(session: Session, *, scan_date: date | None = None) -> int:
    """Scan all users for overdue follow-ups. Returns in-app notifications enqueued."""
    today = scan_date or date.today()
    users = session.query(User).all()
    enqueued = 0

    for user in users:
        applications = (
            session.query(Application, Job)
            .join(Job, Application.job_id == Job.id)
            .filter(Application.user_id == user.id)
            .all()
        )
        email_items: list[dict] = []

        for application, job in applications:
            if application.status in {"rejected", "accepted", "offer"}:
                continue
            first_overdue, second_overdue = _follow_up_flags(application)
            if not first_overdue and not second_overdue:
                continue

            days = days_since_applied(application)
            if days is None:
                continue

            reminder_type = "14d" if second_overdue else "7d"
            draft = render_follow_up_draft(application, job, user)
            enqueue_follow_up_in_app(
                session,
                user,
                application,
                job.company,
                job.title,
                reminder_type=reminder_type,
                days_since=days,
            )
            enqueued += 1
            email_items.append(
                {
                    "company": job.company,
                    "title": job.title,
                    "days": days,
                    "draft_body": draft,
                    "application_id": str(application.id),
                }
            )

        if email_items:
            enqueue_follow_up_email_batch(session, user, email_items, today)

    session.flush()
    log.info("Follow-up scan complete: %d in-app notifications enqueued", enqueued)
    return enqueued
