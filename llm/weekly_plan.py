"""LLM weekly skill plan."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_weekly_skill_plan(
    *,
    missing_skills: list,
    candidate_name: str,
    preferred_roles: list[str],
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    roles = ", ".join(preferred_roles) if preferred_roles else "target roles"
    prompt = f"""Create a 1-week job-search skill plan for {candidate_name} targeting {roles}.

Missing skills data:
{json.dumps(missing_skills, default=str)[:4000]}

Return ONLY JSON:
{{
  "actions": [
    {{"action": "...", "why": "...", "effort": "low|medium|high"}}
  ]
}}

3-5 concrete actions. Prefer resume edits, practice, and apply volume over expensive courses.
"""
    raw = call_llm(prompt, "weekly_skill_plan", user_id, session, max_tokens=1200)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("weekly plan was not a JSON object")
    return data
