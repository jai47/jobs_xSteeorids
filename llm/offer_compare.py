"""LLM offer comparison summary."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_offer_compare(
    *,
    offers: list[dict[str, Any]],
    candidate_name: str,
    preferred_countries: list[str],
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    prefs = ", ".join(preferred_countries) if preferred_countries else "(none)"
    prompt = f"""Compare these job offers/late-stage roles for {candidate_name}.
Preferred countries: {prefs}

Offers JSON:
{json.dumps(offers, default=str)[:6000]}

Return ONLY JSON:
{{
  "summary": "<2-4 sentences>",
  "negotiation_bullets": ["..."]
}}

Be practical. Do not invent salary numbers not in the data.
"""
    raw = call_llm(prompt, "offer_compare", user_id, session, max_tokens=1200)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("offer compare was not a JSON object")
    return data
