"""LLM: patterns narrative summary."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json


def generate_patterns_summary(
    *,
    insights: list[dict[str, Any]],
    reject_reasons: dict[str, int],
    rejected_companies: dict[str, int],
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    prompt = f"""Summarise job-search targeting patterns for the candidate.
Insights: {json.dumps(insights)[:3000]}
Reject reasons: {json.dumps(reject_reasons)}
Rejected companies: {json.dumps(rejected_companies)}

Return ONLY JSON:
{{"summary": "<4-6 sentences with concrete next adjustments>"}}
Be practical. No fluff.
"""
    raw = call_llm(prompt, "patterns_summary", user_id, session, max_tokens=800)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("patterns summary was not a JSON object")
    return data
