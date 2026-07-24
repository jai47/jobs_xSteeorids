"""LLM: company research brief."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_company_research(
    *,
    company: str,
    job_title: str | None,
    candidate_name: str,
    preferred_countries: list[str],
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    prefs = ", ".join(preferred_countries) if preferred_countries else "(none)"
    role = job_title or "(any role)"
    prompt = f"""Write a concise company research brief for {candidate_name} considering {company}
for role: {role}. Preferred countries: {prefs}.

You do not have live web access. Be honest about uncertainty. Do not invent specific funding
rounds, names, or numbers — use directional guidance and what to verify.

Return ONLY JSON:
{{
  "summary": "<3-5 sentences>",
  "funding_or_stage": "<string or null>",
  "leadership_notes": "<string or null>",
  "press_signals": ["what to look up"],
  "comp_signals": ["how to sanity-check pay"],
  "red_flags": ["..."],
  "green_flags": ["..."],
  "questions_to_ask": ["..."]
}}
"""
    raw = call_llm(prompt, "company_research", user_id, session, max_tokens=1400)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("company research was not a JSON object")
    return data
