"""Pydantic schemas for STAR stories."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StoryResponse(BaseModel):
    id: str
    status: str
    title: str
    tags: list[str] = Field(default_factory=list)
    situation: str | None = None
    task: str | None = None
    action: str | None = None
    result: str | None = None
    reflection: str | None = None
    source_job_id: str | None = None
    ai_drafted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StoryListResponse(BaseModel):
    items: list[StoryResponse]
    total: int


class StoryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    tags: list[str] = Field(min_length=1)
    situation: str | None = None
    task: str | None = None
    action: str | None = None
    result: str | None = None
    reflection: str | None = None
    status: str = "draft"


class StoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    tags: list[str] | None = None
    situation: str | None = None
    task: str | None = None
    action: str | None = None
    result: str | None = None
    reflection: str | None = None
    status: str | None = None


class StoryDraftRequest(BaseModel):
    tag: str
    application_id: str | None = None


class ThemesResponse(BaseModel):
    themes: list[str] = Field(default_factory=list)
    status: str = "pending"


class InterviewPrepResponse(BaseModel):
    themes: list[str] = Field(default_factory=list)
    stories: list[StoryResponse] = Field(default_factory=list)
    uncovered_themes: list[str] = Field(default_factory=list)


class StageEventResponse(BaseModel):
    from_status: str | None = None
    to_status: str | None = None
    from_sub: str | None = None
    to_sub: str | None = None
    occurred_at: datetime | None = None


class TimelineResponse(BaseModel):
    events: list[StageEventResponse] = Field(default_factory=list)
