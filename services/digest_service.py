"""Daily digest retrieval for the dashboard."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import DailyDigest, User


def get_today_digest(session: Session, user: User) -> DailyDigest:
    """Return today's digest for the user, or raise NOT_FOUND."""
    digest = (
        session.query(DailyDigest)
        .filter_by(user_id=user.id, digest_date=date.today())
        .first()
    )
    if digest is None:
        raise APIError(
            404,
            "No digest available for today. Run the pipeline first.",
            "NOT_FOUND",
        )
    return digest
