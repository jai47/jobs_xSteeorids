"""Pydantic schemas for resume parsing validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ParsedResumeOutput(BaseModel):
    """Validated LLM output for resume parsing."""

    skills: list[str] = Field(default_factory=list)
    experience_years: int
    previous_titles: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
