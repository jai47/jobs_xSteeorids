"""Pydantic schemas for cover letters (F01)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CoverLetterResponse(BaseModel):
    id: str
    application_id: str
    status: str
    body: str | None = None
    word_count: int = 0
    generation_count: int = 0
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CoverLetterGenerateResponse(BaseModel):
    status: str


class CoverLetterUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CoverLetterAngles(BaseModel):
    why_company: str = ""
    problem_i_solve: str = ""
    my_approach: str = ""
    tone: str = ""
