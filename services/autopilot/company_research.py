"""Deep company research brief (LLM + fail-soft heuristic)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.autopilot import CompanyResearchRequest, CompanyResearchResponse
from db.models import Application, Job, User
from llm.company_research import generate_company_research
from services.autopilot.state import get_app_autopilot, get_user_autopilot, patch_app_autopilot, patch_user_autopilot
from services.llm_generation_guard import enforce_daily_generation_guard


def _slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", company.strip().lower()).strip("-")[:80] or "company"


def _heuristic(company: str, job_title: str | None) -> dict[str, Any]:
    role = f" for {job_title}" if job_title else ""
    return {
        "summary": (
            f"{company} — research brief{role}. Verify funding, leadership, and culture from "
            "primary sources before you apply. This is a lightweight placeholder without live web search."
        ),
        "funding_or_stage": "Unknown — check Crunchbase / company about page",
        "leadership_notes": "Confirm hiring manager and recent leadership changes on LinkedIn",
        "press_signals": ["Search recent news for layoffs, funding, and product launches"],
        "comp_signals": ["Compare levels.fyi / Glassdoor ranges for this title and location"],
        "red_flags": ["Unclear visa policy", "Evergreen posting with no team context"],
        "green_flags": ["Clear product focus", "Transparent eng blog or open roles page"],
        "questions_to_ask": [
            "What does success look like in the first 90 days?",
            "How is the team staffed for this role?",
            "What is the visa / relocation policy?",
        ],
    }


def research_company(
    session: Session,
    user: User,
    payload: CompanyResearchRequest,
) -> CompanyResearchResponse:
    company = payload.company.strip()
    job_title = (payload.job_title or "").strip() or None
    application_id = payload.application_id

    if application_id:
        try:
            app_uuid = uuid.UUID(str(application_id))
        except ValueError as exc:
            raise APIError(422, "Invalid application_id", "VALIDATION_ERROR") from exc
        application = session.get(Application, app_uuid)
        if application is None or application.user_id != user.id:
            raise APIError(404, "Application not found", "NOT_FOUND")
        job = session.get(Job, application.job_id)
        if job is None:
            raise APIError(404, "Job not found", "NOT_FOUND")
        company = job.company
        job_title = job_title or job.title
        cache = get_app_autopilot(application).get("company_research")
        if isinstance(cache, dict) and not payload.force:
            return CompanyResearchResponse(
                company=company,
                job_title=job_title,
                application_id=str(application.id),
                cached=True,
                summary=str(cache.get("summary") or ""),
                funding_or_stage=cache.get("funding_or_stage"),
                leadership_notes=cache.get("leadership_notes"),
                press_signals=list(cache.get("press_signals") or []),
                comp_signals=list(cache.get("comp_signals") or []),
                red_flags=list(cache.get("red_flags") or []),
                green_flags=list(cache.get("green_flags") or []),
                questions_to_ask=list(cache.get("questions_to_ask") or []),
                generated_at=cache.get("generated_at"),
            )

    slug = _slug(company)
    user_cache = get_user_autopilot(user).get("company_research") or {}
    if isinstance(user_cache, dict) and slug in user_cache and not payload.force and not application_id:
        cached = user_cache[slug]
        if isinstance(cached, dict):
            return CompanyResearchResponse(
                company=company,
                job_title=job_title,
                application_id=None,
                cached=True,
                summary=str(cached.get("summary") or ""),
                funding_or_stage=cached.get("funding_or_stage"),
                leadership_notes=cached.get("leadership_notes"),
                press_signals=list(cached.get("press_signals") or []),
                comp_signals=list(cached.get("comp_signals") or []),
                red_flags=list(cached.get("red_flags") or []),
                green_flags=list(cached.get("green_flags") or []),
                questions_to_ask=list(cached.get("questions_to_ask") or []),
                generated_at=cached.get("generated_at"),
            )

    enforce_daily_generation_guard(session, user.id)
    try:
        raw = generate_company_research(
            company=company,
            job_title=job_title,
            candidate_name=user.name,
            preferred_countries=list(user.preferred_countries or []),
            user_id=user.id,
            session=session,
        )
    except (LLMError, Exception):
        raw = _heuristic(company, job_title)

    generated_at = datetime.now(timezone.utc).isoformat()
    stored = {
        "summary": str(raw.get("summary") or _heuristic(company, job_title)["summary"]),
        "funding_or_stage": raw.get("funding_or_stage"),
        "leadership_notes": raw.get("leadership_notes"),
        "press_signals": [str(x) for x in (raw.get("press_signals") or []) if str(x).strip()][:8],
        "comp_signals": [str(x) for x in (raw.get("comp_signals") or []) if str(x).strip()][:8],
        "red_flags": [str(x) for x in (raw.get("red_flags") or []) if str(x).strip()][:8],
        "green_flags": [str(x) for x in (raw.get("green_flags") or []) if str(x).strip()][:8],
        "questions_to_ask": [str(x) for x in (raw.get("questions_to_ask") or []) if str(x).strip()][:8],
        "generated_at": generated_at,
    }

    research_map = dict(user_cache) if isinstance(user_cache, dict) else {}
    research_map[slug] = stored
    patch_user_autopilot(user, company_research=research_map)

    if application_id:
        application = session.get(Application, uuid.UUID(str(application_id)))
        if application and application.user_id == user.id:
            patch_app_autopilot(application, company_research=stored)

    session.flush()
    return CompanyResearchResponse(
        company=company,
        job_title=job_title,
        application_id=str(application_id) if application_id else None,
        cached=False,
        summary=stored["summary"],
        funding_or_stage=stored.get("funding_or_stage"),
        leadership_notes=stored.get("leadership_notes"),
        press_signals=list(stored.get("press_signals") or []),
        comp_signals=list(stored.get("comp_signals") or []),
        red_flags=list(stored.get("red_flags") or []),
        green_flags=list(stored.get("green_flags") or []),
        questions_to_ask=list(stored.get("questions_to_ask") or []),
        generated_at=generated_at,
    )
