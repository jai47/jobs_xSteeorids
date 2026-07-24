"""LLM Autopilot chat."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_chat_reply(
    *,
    message: str,
    candidate_name: str,
    context: dict[str, Any],
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    prompt = f"""You are the job-search Autopilot coach for {candidate_name}.
Be concise (under 120 words). Never claim you sent LinkedIn messages or applied for them.
Suggest concrete next actions from their queue.

User message: {message[:2000]}

Context JSON:
{json.dumps(context, default=str)[:5000]}

Return ONLY JSON:
{{
  "reply": "...",
  "suggested_actions": [
    {{"action": "ensure_packet|message_pack|interview_pack|follow_up|open_today", "label": "...", "application_id": "uuid-or-null"}}
  ]
}}
"""
    raw = call_llm(prompt, "autopilot_chat", user_id, session, max_tokens=900)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("chat was not a JSON object")
    return data
