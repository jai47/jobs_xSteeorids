"""Daily digest routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.digest import DigestResponse
from db.models import User
from services.digest_service import get_today_digest

router = APIRouter(tags=["digest"])


@router.get("/digest/today", response_model=DigestResponse)
def today_digest(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DigestResponse:
    """Return today's digest text and metrics for the authenticated user."""
    digest = get_today_digest(db, user)
    return DigestResponse(
        digest_date=digest.digest_date,
        content_text=digest.content_text,
        metrics_json=digest.metrics_json,
    )
