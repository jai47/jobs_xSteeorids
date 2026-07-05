"""Outbox drainer — SKIP LOCKED batch send with exponential backoff."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from config import settings
from db.models import Notification, User
from services.email.provider import get_email_provider
from services.email.templates import digest_email, follow_up_batch_email

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BATCH_LIMIT = 50


def _backoff_minutes(attempts: int) -> int:
    return 15 * (2 ** attempts)


def _should_send_email(user: User, notification: Notification) -> bool:
    if notification.type == "digest_email":
        return bool(user.notify_digest_email)
    if notification.type == "follow_up":
        return bool(user.notify_followup_email)
    return True


def _render_email(notification: Notification, user: User) -> tuple[str, str, str]:
    payload = notification.payload_json or {}
    if notification.type == "digest_email":
        digest_date = date.fromisoformat(payload.get("digest_date", date.today().isoformat()))
        return digest_email(
            payload.get("user_name", user.name),
            digest_date,
            payload.get("content_text", ""),
            user_id=str(user.id),
        )
    if notification.type == "follow_up":
        items = payload.get("items") or []
        return follow_up_batch_email(
            payload.get("user_name", user.name),
            items,
            user_id=str(user.id),
        )
    subject = payload.get("subject", "Notification")
    body = payload.get("body", "")
    return subject, f"<p>{body}</p>", body


def drain_notification_outbox(session: Session, *, limit: int = BATCH_LIMIT) -> int:
    """Drain pending email notifications. Returns count processed."""
    now = datetime.now(timezone.utc)
    rows = (
        session.query(Notification)
        .filter(
            Notification.status == "pending",
            Notification.channel == "email",
            Notification.scheduled_for <= now,
        )
        .order_by(Notification.scheduled_for)
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )
    if not rows:
        return 0

    provider = get_email_provider()
    processed = 0
    for notification in rows:
        user = session.get(User, notification.user_id)
        if user is None:
            notification.status = "failed"
            notification.attempts = MAX_ATTEMPTS
            continue

        if not _should_send_email(user, notification):
            notification.status = "cancelled"
            notification.sent_at = now
            processed += 1
            continue

        try:
            subject, html, text = _render_email(notification, user)
            provider.send(user.email, subject, html, text)
            notification.status = "sent"
            notification.sent_at = now
            processed += 1
        except Exception as exc:
            log.warning("Email send failed for notification %s: %s", notification.id, exc)
            notification.attempts = (notification.attempts or 0) + 1
            if notification.attempts >= MAX_ATTEMPTS:
                notification.status = "failed"
            else:
                delay = _backoff_minutes(notification.attempts)
                notification.scheduled_for = now + timedelta(minutes=delay)

    session.flush()
    return processed


def mark_in_app_as_sent(session: Session, notification_id) -> None:
    """In-app notifications are 'sent' immediately on insert; this marks feed visibility."""
    row = session.get(Notification, notification_id)
    if row and row.channel == "in_app" and row.status == "pending":
        row.status = "sent"
        row.sent_at = datetime.now(timezone.utc)
        session.flush()
