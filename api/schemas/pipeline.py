"""Pydantic schemas for pipeline API responses."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class PipelineProgressEntry(BaseModel):
    ts: str
    stage: str
    level: str = "info"
    message: str


class PipelineRunResponse(BaseModel):
    id: str
    user_id: str | None = None
    run_date: date
    started_at: datetime | None
    completed_at: datetime | None
    status: str | None
    jobs_discovered: int
    jobs_after_dedup: int
    jobs_scored: int
    top_opportunities: int
    error_stage: str | None
    error_message: str | None
    current_stage: str | None = None
    progress_log: list[PipelineProgressEntry] = Field(default_factory=list)


class PipelineRunListResponse(BaseModel):
    runs: list[PipelineRunResponse]


class LLMUsageResponse(BaseModel):
    total_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    estimated_cost_usd: float
    budget_usd: float = 1.0
    remaining_usd: float = 1.0
    token_balance: int = 1000
    spent_today_tokens: int = 0
