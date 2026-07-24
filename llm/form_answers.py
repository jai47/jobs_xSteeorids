"""LLM: application form answer drafts."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_form_answers(
    *,
    company: str,
    title: str,
    job_description: str,
    questions: list[str],
    candidate_name: str,
    skills: list[str],
    cv_excerpt: str,
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    q_json = json.dumps([{"id": f"q{i}", "question": q} for i, q in enumerate(questions)])
    prompt = f"""Draft copy-paste answers for {candidate_name} applying to {title} at {company}.
Skills: {", ".join(skills[:20]) or "(none)"}
JD excerpt:
{job_description[:4000]}

CV excerpt:
{cv_excerpt[:4000] or "(none)"}

Questions:
{q_json}

Rules:
- Ground answers in CV/skills; do not invent employers or degrees.
- Keep each answer 80–180 words unless the question asks for short.
- User will paste manually — never claim you submitted anything.

Return ONLY JSON:
{{
  "answers": [
    {{"id": "q0", "question": "...", "answer": "...", "tips": "optional edit tip"}}
  ]
}}
"""
    raw = call_llm(prompt, "form_answers", user_id, session, max_tokens=2500)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("form answers was not a JSON object")
    return data
