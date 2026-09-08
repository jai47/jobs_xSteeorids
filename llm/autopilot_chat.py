"""LLM Autopilot chat with visual-aware coaching."""

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
    recent_messages: list[dict[str, Any]] | None = None,
    user_id: uuid.UUID,
    session: Session,
    career_context: str = "",
) -> dict[str, Any]:
    history = json.dumps(recent_messages or [], default=str)[:2500]
    career = (career_context or "").strip()[:7000]
    career_block = (
        f"\nCandidate resume + matched jobs context (use this; do not invent experience):\n{career}\n"
        if career
        else ""
    )
    prompt = f"""You are the job-search Autopilot coach for {candidate_name}.
Speak warmly and clearly (under 140 words). Never claim you sent LinkedIn messages or applied.
Ground advice in the candidate's real resume skills/titles and the matched jobs below when relevant.
The UI already shows visual cards (stats, jobs, checklist) — your reply should complement them,
not repeat every number. Suggest concrete next actions.
{career_block}
Recent conversation:
{history}

User message: {message[:2000]}

Today-queue Context JSON:
{json.dumps(context, default=str)[:4000]}

Return ONLY JSON:
{{
  "reply": "...",
  "mood": "neutral|encouraging|urgent|celebratory",
  "tour_id": "site_tour|apply_flow|follow_ups|jobs_browse|upload_resume|network_outreach|today_focus|analytics|null",
  "suggested_actions": [
    {{
      "action": "ensure_packet|message_pack|interview_pack|follow_up|open_today|open_tracker|open_opportunities|open_networks|open_analytics|start_tour:site_tour",
      "label": "...",
      "application_id": "uuid-or-null",
      "path": "/today|/tracker|/opportunities|/networks|/analytics|null"
    }}
  ]
}}

When the user asks how to use the app, for a walkthrough, or how to apply/follow up/upload resume, set tour_id accordingly.
"""
    raw = call_llm(prompt, "autopilot_chat", user_id, session, max_tokens=1000)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("chat was not a JSON object")
    return data
