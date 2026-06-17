"""Pydantic schemas for daily digest."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel


class DigestResponse(BaseModel):
    digest_date: date
    content_text: str
    metrics_json: dict[str, Any] | None = None
