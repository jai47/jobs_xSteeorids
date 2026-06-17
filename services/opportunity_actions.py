"""Business logic for opportunity listing and user actions."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import Application, Job, ScoredOpportunity, User
from services.resume_tailoring import create_tailored_resume_version, get_active_master_resume

VALID_REJECT_REASONS = {"company", "role", "location", "other"}


def _get_opportunity_for_user(
    session: Session,
    user: User,
    opportunity_id: uuid.UUID,
) -> tuple[ScoredOpportunity, Job]:
    """Load a scored opportunity and its job, scoped to the user."""
    opp = (
        session.query(ScoredOpportunity)
        .filter_by(id=opportunity_id, user_id=user.id)
        .first()
    )
    if opp is None:
        raise APIError(404, "Opportunity not found", "NOT_FOUND")

    job = session.get(Job, opp.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")
    return opp, job


def list_opportunities(
    session: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 25,
    country: str | None = None,
    visa_status: str | None = None,
    classification: str | None = None,
    min_score: float | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[tuple[ScoredOpportunity, Job]], int]:
    """Return paginated scored opportunities with filters."""
    query = (
        session.query(ScoredOpportunity, Job)
        .join(Job, ScoredOpportunity.job_id == Job.id)
        .filter(ScoredOpportunity.user_id == user.id)
        .order_by(ScoredOpportunity.overall_score.desc(), ScoredOpportunity.created_at.desc())
    )

    if country:
        query = query.filter(Job.country == country.upper())
    if visa_status:
        query = query.filter(ScoredOpportunity.visa_status == visa_status)
    if classification:
        query = query.filter(ScoredOpportunity.classification == classification)
    if min_score is not None:
        query = query.filter(ScoredOpportunity.overall_score >= min_score)
    if date_from:
        query = query.filter(ScoredOpportunity.digest_date >= date_from)
    if date_to:
        query = query.filter(ScoredOpportunity.digest_date <= date_to)

    total = query.count()
    offset = max(page - 1, 0) * page_size
    rows = query.offset(offset).limit(page_size).all()
    return rows, total


def approve_opportunity(
    session: Session,
    user: User,
    opportunity_id: uuid.UUID,
) -> tuple[ScoredOpportunity, Application]:
    """Tailor resume, mark approved, and create or update the application."""
    opp, job = _get_opportunity_for_user(session, user, opportunity_id)
    if opp.user_feedback == "approved":
        raise APIError(409, "Opportunity already approved", "CONFLICT")

    master = get_active_master_resume(session, user)
    resume_version = create_tailored_resume_version(session, user, job, master)

    opp.user_feedback = "approved"
    opp.reject_reason = None

    application = (
        session.query(Application)
        .filter_by(job_id=job.id, user_id=user.id)
        .first()
    )
    if application is None:
        application = Application(
            job_id=job.id,
            user_id=user.id,
            resume_version_id=resume_version.id,
            status="approved",
        )
        session.add(application)
    else:
        application.status = "approved"
        application.resume_version_id = resume_version.id

    session.flush()
    return opp, application


def reject_opportunity(
    session: Session,
    user: User,
    opportunity_id: uuid.UUID,
    reason: str,
) -> ScoredOpportunity:
    """Reject an opportunity and optionally update user blacklists."""
    if reason not in VALID_REJECT_REASONS:
        raise APIError(422, f"Invalid reject reason: {reason}", "VALIDATION_ERROR")

    opp, job = _get_opportunity_for_user(session, user, opportunity_id)
    opp.user_feedback = "rejected"
    opp.reject_reason = reason

    companies = list(user.blacklisted_companies or [])
    roles = list(user.blacklisted_roles or [])
    locations = list(user.blacklisted_locations or [])

    if reason == "company" and job.company not in companies:
        companies.append(job.company)
        user.blacklisted_companies = companies
    elif reason == "role" and job.title not in roles:
        roles.append(job.title)
        user.blacklisted_roles = roles
    elif reason == "location" and job.country:
        code = job.country.upper()
        if code not in locations:
            locations.append(code)
            user.blacklisted_locations = locations

    session.flush()
    return opp


def skip_opportunity(
    session: Session,
    user: User,
    opportunity_id: uuid.UUID,
) -> ScoredOpportunity:
    """Mark an opportunity as skipped."""
    opp, _job = _get_opportunity_for_user(session, user, opportunity_id)
    opp.user_feedback = "skipped"
    opp.reject_reason = None
    session.flush()
    return opp
