"""LLM: suggest who to find at a company + LinkedIn people-search URLs."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from llm.client import call_llm, parse_llm_json

MAX_JD_CHARS = 4000


def linkedin_people_search_url(keywords: str) -> str:
    """Build a LinkedIn people search URL the user opens while logged in."""
    return (
        "https://www.linkedin.com/search/results/people/"
        f"?keywords={quote_plus(keywords.strip())}&origin=GLOBAL_SEARCH_HEADER"
    )


def build_find_network_prompt(
    *,
    company: str,
    job_title: str | None,
    job_description: str | None,
    candidate_name: str,
    skills: list[str],
) -> str:
    skills_line = ", ".join(skills[:20]) if skills else "(none listed)"
    jd = (job_description or "").strip()[:MAX_JD_CHARS]
    title = job_title or "a relevant role"

    return f"""You help job seekers network on LinkedIn like NxtJob's Find Network.

Company: {company}
Target role: {title}
Candidate: {candidate_name}
Candidate skills: {skills_line}
Job description excerpt:
{jd or "(none)"}

Propose 4-6 people-search strategies (not specific real names — LinkedIn search queries).
Focus on: recruiters hiring for this role, hiring managers, employees in the same function,
alumni/referrers, and optionally agency recruiters if relevant.

Return ONLY valid JSON:
{{
  "strategy_summary": "<2 sentences>",
  "suggestions": [
    {{
      "role_tag": "recruiter|hiring_manager|employee|agency|other",
      "title_query": "<keywords to type in LinkedIn people search, include company name>",
      "why": "<one sentence>",
      "priority": <1-5, 1=highest>
    }}
  ]
}}
"""


def generate_find_network_suggestions(
    *,
    company: str,
    job_title: str | None,
    job_description: str | None,
    candidate_name: str,
    skills: list[str],
    user_id: uuid.UUID,
    session: Session,
) -> dict[str, Any]:
    prompt = build_find_network_prompt(
        company=company,
        job_title=job_title,
        job_description=job_description,
        candidate_name=candidate_name,
        skills=skills,
    )
    raw = call_llm(prompt, "linkedin_find_network", user_id, session, max_tokens=1200)
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        raise ValueError("Find-network response was not a JSON object")
    return data
