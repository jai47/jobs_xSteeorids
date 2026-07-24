"""LinkedIn profile coach + find-network suggestions (no LinkedIn scraping)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.linkedin_insights import (
    FindNetworkRequest,
    FindNetworkResponse,
    ImportContactsRequest,
    ImportContactsResponse,
    LinkedInProfileAnalyzeRequest,
    LinkedInProfileAnalysisResponse,
    NetworkSearchSuggestion,
    ProfileSectionScore,
)
from api.schemas.network import NetworkContactCreate
from db.models import Application, Job, NetworkContact, User
from llm.linkedin_find_network import (
    generate_find_network_suggestions,
    linkedin_people_search_url,
)
from llm.linkedin_profile import analyze_linkedin_profile_text
from services.llm_generation_guard import enforce_daily_generation_guard
from services.network_contacts import create_contact, to_response_dict

VALID_SECTION_STATUSES = frozenset({"strong", "improve", "missing"})
VALID_ROLE_TAGS = frozenset({"recruiter", "hiring_manager", "employee", "agency", "other"})
VALID_PROFILE_SOURCES = frozenset({"pasted_profile", "extension"})


def _clamp_score(value: Any) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))


def _normalize_analysis(data: dict[str, Any], *, source: str = "pasted_profile") -> dict[str, Any]:
    sections_raw = data.get("sections") or []
    sections: list[dict[str, Any]] = []
    if isinstance(sections_raw, list):
        for item in sections_raw:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "improve").lower()
            if status not in VALID_SECTION_STATUSES:
                status = "improve"
            sections.append(
                {
                    "section": str(item.get("section") or "unknown"),
                    "score": _clamp_score(item.get("score")),
                    "status": status,
                    "feedback": str(item.get("feedback") or "").strip() or "No feedback.",
                    "suggested_rewrite": (
                        str(item["suggested_rewrite"]).strip()
                        if item.get("suggested_rewrite")
                        else None
                    ),
                }
            )

    quick_wins = [
        str(w).strip()
        for w in (data.get("quick_wins") or [])
        if str(w).strip()
    ][:8]

    src = source if source in VALID_PROFILE_SOURCES else "pasted_profile"
    return {
        "overall_score": _clamp_score(data.get("overall_score")),
        "summary": str(data.get("summary") or "").strip() or "Analysis complete.",
        "headline_suggestion": (
            str(data["headline_suggestion"]).strip()
            if data.get("headline_suggestion")
            else None
        ),
        "about_suggestion": (
            str(data["about_suggestion"]).strip() if data.get("about_suggestion") else None
        ),
        "quick_wins": quick_wins,
        "sections": sections,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source": src,
    }


def _guess_role_tag(headline: str | None, explicit: str | None) -> str:
    if explicit and explicit in VALID_ROLE_TAGS:
        return explicit
    text = (headline or "").lower()
    if any(k in text for k in ("recruiter", "talent acquisition", "sourcer", "staffing")):
        return "recruiter"
    if any(k in text for k in ("hiring manager", "head of", "director", "vp ", "vice president")):
        return "hiring_manager"
    if any(k in text for k in ("agency", "recruiting partner", "rpo")):
        return "agency"
    return "employee"


def analysis_to_response(payload: dict[str, Any]) -> LinkedInProfileAnalysisResponse:
    analyzed_at = payload.get("analyzed_at")
    if isinstance(analyzed_at, str):
        try:
            analyzed_at_dt = datetime.fromisoformat(analyzed_at.replace("Z", "+00:00"))
        except ValueError:
            analyzed_at_dt = None
    elif isinstance(analyzed_at, datetime):
        analyzed_at_dt = analyzed_at
    else:
        analyzed_at_dt = None

    return LinkedInProfileAnalysisResponse(
        overall_score=_clamp_score(payload.get("overall_score")),
        summary=str(payload.get("summary") or ""),
        headline_suggestion=payload.get("headline_suggestion"),
        about_suggestion=payload.get("about_suggestion"),
        quick_wins=list(payload.get("quick_wins") or []),
        sections=[
            ProfileSectionScore(**section)
            for section in (payload.get("sections") or [])
            if isinstance(section, dict) and section.get("section")
        ],
        analyzed_at=analyzed_at_dt,
        source=str(payload.get("source") or "pasted_profile"),
    )


def get_saved_profile_analysis(user: User) -> LinkedInProfileAnalysisResponse | None:
    raw = user.linkedin_profile_analysis
    if not isinstance(raw, dict) or not raw:
        return None
    return analysis_to_response(raw)


def analyze_and_store_profile(
    session: Session,
    user: User,
    payload: LinkedInProfileAnalyzeRequest,
) -> LinkedInProfileAnalysisResponse:
    enforce_daily_generation_guard(session, user.id)
    roles = list(payload.target_roles or user.preferred_roles or [])
    skills = list(user.parsed_skills or [])
    try:
        raw = analyze_linkedin_profile_text(
            profile_text=payload.profile_text,
            candidate_name=user.name,
            target_roles=roles,
            resume_skills=skills,
            user_id=user.id,
            session=session,
        )
    except LLMError as exc:
        raise APIError(502, str(exc), "LLM_ERROR") from exc
    except Exception as exc:
        raise APIError(502, f"Failed to analyze LinkedIn profile: {exc}", "LLM_ERROR") from exc

    normalized = _normalize_analysis(raw, source=payload.source)
    user.linkedin_profile_analysis = normalized
    session.flush()
    return analysis_to_response(normalized)


def import_network_contacts(
    session: Session,
    user: User,
    payload: ImportContactsRequest,
) -> ImportContactsResponse:
    """Create network contacts from extension-extracted people (dedupe by LinkedIn URL)."""
    existing_urls = {
        (url or "").rstrip("/").lower()
        for (url,) in session.query(NetworkContact.linkedin_url).filter_by(user_id=user.id).all()
    }
    created: list[dict] = []
    skipped_urls: list[str] = []
    default_company = (payload.company or "").strip() or None

    for item in payload.contacts:
        url_key = item.linkedin_url.rstrip("/").lower()
        if url_key in existing_urls:
            skipped_urls.append(item.linkedin_url)
            continue
        role_tag = _guess_role_tag(item.headline, item.role_tag)
        notes = None
        if item.headline:
            notes = f"Imported via {payload.source}. Headline: {item.headline.strip()[:300]}"
        try:
            contact = create_contact(
                session,
                user,
                NetworkContactCreate(
                    person_name=item.person_name,
                    linkedin_url=item.linkedin_url,
                    role_tag=role_tag,  # type: ignore[arg-type]
                    application_id=payload.application_id,
                    company=item.company or default_company,
                    notes=notes,
                    generate_draft=payload.generate_drafts,
                ),
            )
        except APIError:
            skipped_urls.append(item.linkedin_url)
            continue
        existing_urls.add(url_key)
        created.append(to_response_dict(contact))

    return ImportContactsResponse(
        created=created,
        skipped=len(skipped_urls),
        skipped_urls=skipped_urls,
    )


def _fallback_suggestions(company: str, job_title: str | None) -> list[NetworkSearchSuggestion]:
    title = job_title or "hiring"
    seeds = [
        ("recruiter", f"Recruiter {company}", f"Talent team recruiting for {company}", 1),
        ("recruiter", f"Technical Recruiter {company}", "Technical recruiters often own eng/ML reqs", 1),
        (
            "hiring_manager",
            f"{title} Manager {company}",
            "Managers who own the role can refer or interview",
            2,
        ),
        (
            "employee",
            f"{title} {company}",
            "Peers in the same function are strong referral paths",
            2,
        ),
        ("employee", f"Software Engineer {company}", "Engineers can introduce you to the hiring team", 3),
    ]
    return [
        NetworkSearchSuggestion(
            role_tag=tag,
            title_query=query,
            why=why,
            linkedin_search_url=linkedin_people_search_url(query),
            priority=priority,
        )
        for tag, query, why, priority in seeds
    ]


def find_network_suggestions(
    session: Session,
    user: User,
    payload: FindNetworkRequest,
) -> FindNetworkResponse:
    enforce_daily_generation_guard(session, user.id)

    company = payload.company.strip()
    job_title = (payload.job_title or "").strip() or None
    job_description = payload.job_description

    if payload.application_id:
        try:
            application_id = uuid.UUID(str(payload.application_id))
        except ValueError as exc:
            raise APIError(422, "Invalid application_id", "VALIDATION_ERROR") from exc
        application = (
            session.query(Application)
            .filter_by(id=application_id, user_id=user.id)
            .first()
        )
        if application is None:
            raise APIError(404, "Application not found", "NOT_FOUND")
        job = session.get(Job, application.job_id)
        if job is not None:
            company = company or job.company
            job_title = job_title or job.title
            job_description = job_description or job.description

    try:
        raw = generate_find_network_suggestions(
            company=company,
            job_title=job_title,
            job_description=job_description,
            candidate_name=user.name,
            skills=list(user.parsed_skills or []),
            user_id=user.id,
            session=session,
        )
        suggestions: list[NetworkSearchSuggestion] = []
        for item in raw.get("suggestions") or []:
            if not isinstance(item, dict):
                continue
            query = str(item.get("title_query") or "").strip()
            if not query:
                continue
            tag = str(item.get("role_tag") or "other").lower()
            if tag not in VALID_ROLE_TAGS:
                tag = "other"
            try:
                priority = int(item.get("priority") or 3)
            except (TypeError, ValueError):
                priority = 3
            suggestions.append(
                NetworkSearchSuggestion(
                    role_tag=tag,
                    title_query=query,
                    why=str(item.get("why") or "Relevant networking target").strip(),
                    linkedin_search_url=linkedin_people_search_url(query),
                    priority=max(1, min(5, priority)),
                )
            )
        suggestions.sort(key=lambda s: s.priority)
        if not suggestions:
            suggestions = _fallback_suggestions(company, job_title)
        summary = str(raw.get("strategy_summary") or "").strip() or (
            f"Search LinkedIn for recruiters and peers related to {job_title or 'this role'} at {company}."
        )
    except LLMError:
        suggestions = _fallback_suggestions(company, job_title)
        summary = (
            f"LLM unavailable — using starter searches for {company}. "
            "Open LinkedIn while logged in, then add real people to My Networks."
        )
    except Exception:
        suggestions = _fallback_suggestions(company, job_title)
        summary = f"Starter LinkedIn searches for networking at {company}."

    return FindNetworkResponse(
        company=company,
        job_title=job_title,
        strategy_summary=summary,
        suggestions=suggestions,
    )
