"""Paste-JD auto-pipeline: create job → score → optional approve/tailor."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from api.deps import APIError
from api.schemas.autopilot import AutoPipelineRequest, AutoPipelineResponse, AutoPipelineScores
from core.text import extract_skills
from db.models import Application, Job, ScoredOpportunity, User
from pipeline.stages.fit_scorer import score_fit
from pipeline.stages.job_enrichment import enrich_job_row
from pipeline.stages.overall_scorer import score_overall
from pipeline.stages.visa_scorer import score_visa
from services.opportunity_actions import approve_opportunity
from services.resume_tailoring import create_tailored_resume_version, get_active_master_resume


def _synthetic_url(external_id: str) -> str:
    return f"https://manual.career-copilot.local/jobs/{external_id}"


def _normalise_url(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    url = str(raw).strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise APIError(422, "Invalid job URL", "VALIDATION_ERROR")
    return url


def _guess_title_company(description: str, title: str | None, company: str | None) -> tuple[str, str]:
    lines = [ln.strip() for ln in description.splitlines() if ln.strip()]
    guessed_title = (title or "").strip()
    guessed_company = (company or "").strip()

    if not guessed_title and lines:
        # Prefer lines that look like role titles (short, no "http")
        for line in lines[:8]:
            if len(line) < 120 and "http" not in line.lower() and not line.lower().startswith("about"):
                guessed_title = line[:200]
                break
        if not guessed_title:
            guessed_title = lines[0][:200]

    if not guessed_company:
        company_match = re.search(
            r"(?:company|employer|at)\s*[:\-]\s*(.+)$",
            description,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if company_match:
            guessed_company = company_match.group(1).strip()[:200]
        elif len(lines) >= 2 and len(lines[1]) < 80:
            guessed_company = lines[1][:200]

    if not guessed_title:
        guessed_title = "Untitled role"
    if not guessed_company:
        guessed_company = "Unknown company"
    return guessed_title, guessed_company


def _job_dict_for_scoring(job: Job) -> dict:
    return {
        "title": job.title,
        "company": job.company,
        "country": job.country,
        "remote_type": job.remote_type,
        "description": job.description or "",
        "skills_required": list(job.skills_required or []),
        "experience_min": job.experience_min,
        "visa_mentioned": bool(job.visa_mentioned),
        "visa_keywords": list(job.visa_keywords or []),
    }


def run_auto_pipeline(
    session: Session,
    user: User,
    payload: AutoPipelineRequest,
) -> AutoPipelineResponse:
    """Score a pasted JD; optionally approve + tailor into the tracker."""
    description = payload.description.strip()
    if len(description) < 40:
        raise APIError(422, "Description must be at least 40 characters", "VALIDATION_ERROR")

    title, company = _guess_title_company(description, payload.title, payload.company)
    url = _normalise_url(payload.url)
    external_id = hashlib.sha256(
        f"{user.id}:{company}:{title}:{description[:500]}".encode("utf-8")
    ).hexdigest()[:32]

    # Prefer an existing job with the same URL; never overwrite board-sourced rows.
    job: Job | None = None
    if url:
        job = session.query(Job).filter(Job.url == url).first()

    if job is None:
        job = (
            session.query(Job)
            .filter(Job.source == "manual", Job.external_id == external_id)
            .first()
        )

    skills = extract_skills(description)
    if job is None:
        job = Job(
            source="manual",
            external_id=external_id,
            url=url or _synthetic_url(external_id),
            company=company,
            title=title,
            country=(payload.country or None),
            city=None,
            remote_type=payload.remote_type,
            description=description,
            skills_required=skills,
            visa_mentioned="visa" in description.lower() or "sponsor" in description.lower(),
            is_active=True,
            is_stale=False,
            posted_at=date.today(),
            last_verified=date.today(),
        )
        session.add(job)
        session.flush()
        enrich_job_row(session, job)
    elif job.source == "manual":
        job.company = company
        job.title = title
        job.description = description
        job.skills_required = skills or list(job.skills_required or [])
        if payload.country:
            job.country = payload.country
        if payload.remote_type:
            job.remote_type = payload.remote_type
        job.is_active = True
        job.is_stale = False
        enrich_job_row(session, job)
    # else: reuse board job as-is for scoring

    job_dict = _job_dict_for_scoring(job)
    fit = score_fit(job_dict, user)
    visa = score_visa(job_dict, user)
    overall = score_overall(fit, visa)

    today = date.today()
    opp = (
        session.query(ScoredOpportunity)
        .filter_by(job_id=job.id, user_id=user.id, digest_date=today)
        .first()
    )
    if opp is None:
        opp = ScoredOpportunity(
            job_id=job.id,
            user_id=user.id,
            digest_date=today,
        )
        session.add(opp)

    opp.score_skill_match = fit["score_skill_match"]
    opp.score_role_match = fit["score_role_match"]
    opp.score_experience = fit["score_experience"]
    opp.score_country_pref = fit["score_country_pref"]
    opp.score_remote_pref = fit["score_remote_pref"]
    opp.score_fit = fit["score_fit"]
    opp.fit_reasoning = fit["fit_reasoning"]
    opp.score_visa = visa["score_visa"]
    opp.visa_status = visa["visa_status"]
    opp.visa_reasoning = visa["visa_reasoning"]
    opp.overall_score = overall["overall_score"]
    opp.classification = overall["classification"]
    session.flush()

    application_id: str | None = None
    resume_version_id: str | None = None
    tailored = False

    if payload.approve:
        master = get_active_master_resume(session, user)
        if master is None:
            raise APIError(
                422,
                "Upload an active master resume before approving/tailoring",
                "VALIDATION_ERROR",
            )
        # Mark opportunity approved via shared path when not already approved
        if opp.user_feedback != "approved":
            _, application = approve_opportunity(session, user, opp.id)
        else:
            application = (
                session.query(Application)
                .filter_by(job_id=job.id, user_id=user.id)
                .first()
            )
            if application is None:
                resume = create_tailored_resume_version(session, user, job, master)
                application = Application(
                    job_id=job.id,
                    user_id=user.id,
                    resume_version_id=resume.id,
                    status="approved",
                )
                session.add(application)
                session.flush()
            elif not application.resume_version_id:
                resume = create_tailored_resume_version(session, user, job, master)
                application.resume_version_id = resume.id
                session.flush()

        application_id = str(application.id)
        resume_version_id = str(application.resume_version_id) if application.resume_version_id else None
        tailored = bool(application.resume_version_id)
    elif payload.track:
        application = (
            session.query(Application)
            .filter_by(job_id=job.id, user_id=user.id)
            .first()
        )
        if application is None:
            application = Application(
                job_id=job.id,
                user_id=user.id,
                status="approved",
            )
            session.add(application)
            session.flush()
        application_id = str(application.id)
        if opp.user_feedback is None:
            opp.user_feedback = "approved"

    session.flush()
    return AutoPipelineResponse(
        opportunity_id=str(opp.id),
        job_id=str(job.id),
        application_id=application_id,
        resume_version_id=resume_version_id,
        company=job.company,
        title=job.title,
        url=job.url,
        overall_score=float(opp.overall_score or 0),
        classification=opp.classification or "optional",
        scores=AutoPipelineScores(
            skill_match=fit["score_skill_match"],
            role_match=fit["score_role_match"],
            experience=fit["score_experience"],
            country_pref=fit["score_country_pref"],
            remote_pref=fit["score_remote_pref"],
            fit=fit["score_fit"],
            visa=float(visa["score_visa"]),
        ),
        fit_reasoning=fit["fit_reasoning"],
        visa_status=visa["visa_status"],
        visa_reasoning=visa["visa_reasoning"],
        tailored=tailored,
        created_at=datetime.now(timezone.utc),
    )
