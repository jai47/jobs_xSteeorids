"""LLM mock interview questions for an application."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_mock_interview(
    *,
    company: str,
    job_title: str,
    job_description: str | None,
    themes: list[str],
    candidate_name: str,
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    themes_line = ", ".join(themes) if themes else "(none extracted yet)"
    jd = (job_description or "")[:3500]
    prompt = f"""Create a mock interview pack for {candidate_name} interviewing for {job_title} at {company}.

Themes to cover: {themes_line}
JD excerpt:
{jd or "(none)"}

Return ONLY JSON:
{{
  "questions": [
    {{"question": "...", "tip": "...", "related_theme": "..."}}
  ],
  "thank_you_note": "<short thank-you email body with optional Subject line>"
}}

Provide 5-7 behavioral/technical questions. Tips should be one sentence. Do not invent the candidate's past employers.
"""
    raw = call_llm(prompt, "interview_mock", user_id, session, max_tokens=1800)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("mock interview was not a JSON object")
    return data
