"""Append-only application stage event log (F11)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models import ApplicationStageEvent


def append_stage_event(
    session: Session,
    application_id: uuid.UUID,
    *,
    from_status: str | None,
    to_status: str | None,
    from_sub: str | None,
    to_sub: str | None,
    occurred_at: datetime | None = None,
) -> ApplicationStageEvent:
    event = ApplicationStageEvent(
        application_id=application_id,
        from_status=from_status,
        to_status=to_status,
        from_sub=from_sub,
        to_sub=to_sub,
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )
    session.add(event)
    session.flush()
    return event


def list_timeline_events(session: Session, application_id: uuid.UUID) -> list[ApplicationStageEvent]:
    return (
        session.query(ApplicationStageEvent)
        .filter_by(application_id=application_id)
        .order_by(ApplicationStageEvent.occurred_at.asc())
        .all()
    )


def time_in_stage_days(session: Session, application_id: uuid.UUID) -> int | None:
    latest = (
        session.query(ApplicationStageEvent)
        .filter_by(application_id=application_id)
        .order_by(ApplicationStageEvent.occurred_at.desc())
        .first()
    )
    if latest is None or latest.occurred_at is None:
        return None
    occurred = latest.occurred_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - occurred
    return max(delta.days, 0)
