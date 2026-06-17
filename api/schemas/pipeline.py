"""Pydantic schemas for pipeline API responses."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class PipelineRunResponse(BaseModel):
    id: str
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


class PipelineRunListResponse(BaseModel):
    runs: list[PipelineRunResponse]


class LLMUsageResponse(BaseModel):
    total_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    estimated_cost_usd: float
