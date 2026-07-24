"""LLM: portfolio project score."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_project_score(
    *,
    title: str,
    description: str,
    estimated_hours: float | None,
    preferred_roles: list[str],
    skills: list[str],
    candidate_name: str,
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    prompt = f"""Score this portfolio project idea for {candidate_name}.
Title: {title}
Description: {description[:2500]}
Estimated hours: {estimated_hours}
Preferred roles: {preferred_roles}
Skills: {skills[:30]}

Return ONLY JSON:
{{
  "score": 0-100,
  "verdict": "build" | "maybe" | "skip",
  "summary": "...",
  "why": ["..."],
  "scope_tips": ["..."],
  "resume_bullets": ["template bullets with [brackets] for metrics"]
}}
"""
    raw = call_llm(prompt, "project_score", user_id, session, max_tokens=1000)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("project score was not a JSON object")
    return data
