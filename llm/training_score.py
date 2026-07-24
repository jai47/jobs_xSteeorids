"""LLM: training / course score."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_training_score(
    *,
    title: str,
    description: str,
    cost_hours: float | None,
    cost_money: float | None,
    url: str | None,
    preferred_roles: list[str],
    skills: list[str],
    candidate_name: str,
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    prompt = f"""Score this course/cert for {candidate_name}.
Title: {title}
Description: {description[:2500]}
Hours: {cost_hours}
Money: {cost_money}
URL: {url}
Preferred roles: {preferred_roles}
Skills: {skills[:30]}

Return ONLY JSON:
{{
  "score": 0-100,
  "verdict": "worth_it" | "maybe" | "skip",
  "summary": "...",
  "why": ["..."],
  "opportunity_cost": ["..."],
  "better_alternatives": ["..."]
}}
"""
    raw = call_llm(prompt, "training_score", user_id, session, max_tokens=1000)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("training score was not a JSON object")
    return data
