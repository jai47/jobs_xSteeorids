"""Pydantic schemas for notifications."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NotificationItem(BaseModel):
    id: str
    type: str
    title: str
    body: str
    link_path: str | None = None
    read_at: datetime | None = None
    created_at: datetime | None = None


class NotificationListResponse(BaseModel):
    items: list[NotificationItem] = Field(default_factory=list)
    unread_count: int = 0


class FollowUpDraftResponse(BaseModel):
    body: str
    days_since_applied: int
    personalised: bool = False
