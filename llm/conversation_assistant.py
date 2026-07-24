"""LLM: LinkedIn conversation replies in the user's voice."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_conversation_replies(
    *,
    thread_text: str,
    candidate_name: str,
    voice_notes: str | None,
    company: str | None,
    job_title: str | None,
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    voice = (voice_notes or "Warm, concise, professional; no buzzwords.").strip()[:1500]
    ctx = f"{job_title} at {company}" if company else "a career conversation"
    prompt = f"""You are a LinkedIn Conversation Assistant for {candidate_name} about {ctx}.

Write replies that sound like them: {voice}

Incoming thread (oldest → newest):
<<<THREAD>>>
{thread_text[:7000]}
<<<END>>>

Return ONLY JSON:
{{
  "drafts": [
    {{"tone": "warm|concise|assertive", "body": "..."}}
  ],
  "intent": "<what the other person wants>",
  "suggested_next_status": "accepted|replied|closed|null"
}}

2-3 drafts. Plain text. Do not invent meeting times not offered. No emoji unless the thread uses them.
"""
    raw = call_llm(prompt, "conversation_assistant", user_id, session, max_tokens=1600)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("conversation assistant did not return JSON")
    return data
