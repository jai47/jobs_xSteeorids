"""Pydantic schemas for resume parsing and tailoring validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ParsedResumeOutput(BaseModel):
    """Validated LLM output for resume parsing."""

    skills: list[str] = Field(default_factory=list)
    experience_years: int
    previous_titles: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class TailoredResumeOutput(BaseModel):
    """Validated LLM output for resume tailoring."""

    tailored_markdown: str
    json_resume: dict[str, Any] = Field(default_factory=dict)
    ats_score_before: int = Field(ge=0, le=100)
    ats_score_after: int = Field(ge=0, le=100)
    keywords_added: list[str] = Field(default_factory=list)
    skill_gaps: list[str] = Field(default_factory=list)
