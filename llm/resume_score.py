"""LLM resume score for master resume."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def analyze_resume_score(
    *,
    resume_text: str,
    candidate_name: str,
    target_roles: list[str],
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    roles = ", ".join(target_roles) if target_roles else "general tech roles"
    body = resume_text[:18000]
    prompt = f"""Score this resume for {candidate_name} targeting: {roles}.

Return ONLY JSON:
{{
  "overall_score": <0-100>,
  "summary": "<2 sentences>",
  "quick_wins": ["..."],
  "sections": [
    {{"section": "summary|experience|skills|education|ats_keywords", "score": <0-100>, "feedback": "..."}}
  ]
}}

Do not invent employers or metrics not in the text.

<<<RESUME>>>
{body}
<<<END>>>
"""
    raw = call_llm(prompt, "resume_score", user_id, session, max_tokens=1800)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("resume score was not a JSON object")
    return data
