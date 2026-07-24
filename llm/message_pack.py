"""LLM: full outreach message pack for an application."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json

MAX_JD = 3000


def generate_message_pack(
    *,
    company: str,
    job_title: str,
    job_description: str | None,
    candidate_name: str,
    skills: list[str],
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    skills_line = ", ".join(skills[:20]) if skills else "(none)"
    jd = (job_description or "")[:MAX_JD]
    prompt = f"""You help job seekers with outreach sequences (LinkedIn + email).

Candidate: {candidate_name}
Skills: {skills_line}
Role: {job_title} at {company}
JD excerpt:
{jd or "(none)"}

Return ONLY valid JSON with messages for keys:
connect, follow_up_d7, follow_up_d14, referral, thank_you, any_update.

Rules:
- connect, follow_up_d7, referral: LinkedIn notes ≤300 characters, plain text, no emoji.
- follow_up_d14, thank_you, any_update: short emails; may include a Subject: line.
- Do not invent employers, metrics, or mutual connections.

{{
  "messages": [
    {{"key": "connect", "body": "..."}},
    {{"key": "follow_up_d7", "body": "..."}},
    {{"key": "follow_up_d14", "body": "..."}},
    {{"key": "referral", "body": "..."}},
    {{"key": "thank_you", "body": "..."}},
    {{"key": "any_update", "body": "..."}}
  ]
}}
"""
    raw = call_llm(prompt, "message_pack", user_id, session, max_tokens=2000)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("message pack was not a JSON object")
    return data
