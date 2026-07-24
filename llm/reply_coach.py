"""LLM reply drafts for recruiter messages."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_reply_drafts(
    *,
    message: str,
    candidate_name: str,
    company: str | None,
    job_title: str | None,
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    ctx = f"{job_title or 'role'} at {company}" if company else "an open role"
    prompt = f"""You help {candidate_name} reply to a recruiter/hiring message about {ctx}.

Incoming message:
<<<MSG>>>
{message[:6000]}
<<<END>>>

Return ONLY JSON:
{{
  "drafts": [
    {{"tone": "professional|warm|concise", "body": "..."}}
  ],
  "suggested_status": "applied|interviewing|offer|null",
  "next_steps": ["..."]
}}

Provide 2-3 reply drafts. Do not invent interview times the message did not offer. Plain text.
"""
    raw = call_llm(prompt, "reply_coach", user_id, session, max_tokens=1500)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("reply coach was not a JSON object")
    return data
