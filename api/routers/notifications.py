"""Notification feed and unsubscribe routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from api.deps import APIError, get_current_user, get_db
from api.schemas.notification import NotificationItem, NotificationListResponse
from db.models import User
from services.notifications.feed import list_notifications, mark_all_read, mark_notification_read
from services.notifications.unsubscribe import verify_unsubscribe_token

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _item_from_row(row) -> NotificationItem:
    payload = row.payload_json or {}
    return NotificationItem(
        id=str(row.id),
        type=row.type,
        title=payload.get("title", ""),
        body=payload.get("body", ""),
        link_path=payload.get("link_path"),
        read_at=row.read_at,
        created_at=row.created_at,
    )


@router.get("", response_model=NotificationListResponse)
def get_notifications(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    unread_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
) -> NotificationListResponse:
    rows, unread_count = list_notifications(db, user, unread_only=unread_only, page=page)
    return NotificationListResponse(
        items=[_item_from_row(row) for row in rows],
        unread_count=unread_count,
    )


@router.post("/{notification_id}/read", status_code=204)
def read_notification(
    notification_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    mark_notification_read(db, user, notification_id)
    return Response(status_code=204)


@router.post("/read-all", status_code=204)
def read_all_notifications(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    mark_all_read(db, user)
    return Response(status_code=204)


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(
    token: str = Query(...),
    db: Annotated[Session, Depends(get_db)] = ...,
) -> HTMLResponse:
    try:
        user_id, channel = verify_unsubscribe_token(token)
    except ValueError as exc:
        raise APIError(400, str(exc), "VALIDATION_ERROR") from exc

    user = db.get(User, user_id)
    if user is None:
        raise APIError(404, "User not found", "NOT_FOUND")

    if channel == "digest":
        user.notify_digest_email = False
    elif channel == "followup":
        user.notify_followup_email = False
    db.flush()

    label = "digest" if channel == "digest" else "follow-up"
    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;padding:2rem">
<h1>Unsubscribed</h1>
<p>You will no longer receive {label} emails from AI Career Copilot.</p>
<p>In-app notifications remain enabled.</p>
</body></html>"""
    return HTMLResponse(content=html)
