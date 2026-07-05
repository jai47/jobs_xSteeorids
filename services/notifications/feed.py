"""In-app notification feed queries."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from db.models import Notification, User

PAGE_SIZE = 30


def list_notifications(
    session: Session,
    user: User,
    *,
    unread_only: bool = False,
    page: int = 1,
) -> tuple[list[Notification], int]:
    query = session.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.channel == "in_app",
        Notification.status == "sent",
    )
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    unread_count = (
        session.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.channel == "in_app",
            Notification.status == "sent",
            Notification.read_at.is_(None),
        )
        .count()
    )
    offset = max(page - 1, 0) * PAGE_SIZE
    rows = (
        query.order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(PAGE_SIZE)
        .all()
    )
    return rows, unread_count


def mark_notification_read(session: Session, user: User, notification_id: uuid.UUID) -> None:
    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user.id or row.channel != "in_app":
        from api.deps import APIError

        raise APIError(404, "Notification not found", "NOT_FOUND")
    from datetime import datetime, timezone

    row.read_at = datetime.now(timezone.utc)
    session.flush()


def mark_all_read(session: Session, user: User) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    (
        session.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.channel == "in_app",
            Notification.read_at.is_(None),
        )
        .update({"read_at": now}, synchronize_session=False)
    )
    session.flush()
