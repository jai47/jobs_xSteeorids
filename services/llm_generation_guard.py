"""Shared daily LLM generation guard (30/user/day) for cover letters, themes, etc."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import LLMUsage

DAILY_GENERATION_LIMIT = 30
GENERATION_PURPOSES = frozenset(
    {
        "cover_letter",
        "star_themes",
        "follow_up_personalise",
        "resume_tailoring",
    }
)


def _seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = datetime.combine(now.date(), time.min, tzinfo=timezone.utc) + timedelta(days=1)
    return max(1, int((tomorrow - now).total_seconds()))


def count_daily_generations(session: Session, user_id: uuid.UUID) -> int:
    today = date.today()
    return (
        session.query(func.count(LLMUsage.id))
        .filter(
            LLMUsage.user_id == user_id,
            LLMUsage.call_purpose.in_(GENERATION_PURPOSES),
            func.date(LLMUsage.created_at) == today,
        )
        .scalar()
        or 0
    )


def enforce_daily_generation_guard(session: Session, user_id: uuid.UUID) -> None:
    """Raise 429 if the user exceeded the daily generation cap."""
    used = count_daily_generations(session, user_id)
    if used >= DAILY_GENERATION_LIMIT:
        raise APIError(
            429,
            "Daily LLM generation limit reached",
            "RATE_LIMITED",
            retry_after_seconds=_seconds_until_utc_midnight(),
        )
