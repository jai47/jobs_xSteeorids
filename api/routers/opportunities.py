"""Scored opportunity routes."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.opportunity import (
    LegitimacyFlag,
    OpportunityActionResponse,
    OpportunityDetail,
    OpportunityListResponse,
    OpportunitySummary,
    RepostInfo,
    RejectRequest,
    SalaryInfo,
)
from db.models import Job, ScoredOpportunity, User
from services.opportunity_actions import (
    approve_opportunity,
    list_opportunities,
    reject_opportunity,
    skip_opportunity,
)
from services.approval_enrichment import run_cover_letter_enrichment, run_theme_extraction

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


def _salary_info(job: Job) -> SalaryInfo | None:
    if not any([job.salary_min, job.salary_max, job.salary_usd_min, job.salary_usd_max]):
        return None
    return SalaryInfo(
        min=job.salary_min,
        max=job.salary_max,
        currency=job.salary_currency,
        period=job.salary_period,
        usd_min=job.salary_usd_min,
        usd_max=job.salary_usd_max,
        currency_assumed=bool(job.salary_currency_assumed),
    )


def _repost_info(job: Job, db: Session) -> RepostInfo:
    if not job.repost_of_job_id:
        return RepostInfo(is_repost=False)
    original = db.get(Job, job.repost_of_job_id)
    first_seen = None
    if original:
        first_seen = original.posted_at or (
            original.created_at.date() if original.created_at else None
        )
    count = 1
    if job.dedup_fingerprint:
        count = (
            db.query(Job)
            .filter(Job.dedup_fingerprint == job.dedup_fingerprint)
            .count()
        )
    return RepostInfo(is_repost=True, first_seen=first_seen, repost_count=count)


def _summary(opp: ScoredOpportunity, job: Job, db: Session) -> OpportunitySummary:
    return OpportunitySummary(
        id=str(opp.id),
        job_id=str(job.id),
        company=job.company,
        title=job.title,
        country=job.country,
        city=job.city,
        remote_type=job.remote_type,
        salary_display=job.salary_display,
        overall_score=opp.overall_score,
        classification=opp.classification,
        visa_status=opp.visa_status,
        score_visa=opp.score_visa,
        score_skill_match=opp.score_skill_match,
        score_role_match=opp.score_role_match,
        score_experience=opp.score_experience,
        score_country_pref=opp.score_country_pref,
        score_remote_pref=opp.score_remote_pref,
        score_fit=opp.score_fit,
        user_feedback=opp.user_feedback,
        digest_date=opp.digest_date,
        created_at=opp.created_at,
        url=job.url,
        is_stale=bool(job.is_stale),
        archetype=job.archetype,
        salary=_salary_info(job),
        legitimacy_flags=[
            LegitimacyFlag(**flag) for flag in (job.legitimacy_flags or []) if isinstance(flag, dict)
        ],
        repost=_repost_info(job, db),
    )


def _detail(opp: ScoredOpportunity, job: Job, db: Session) -> OpportunityDetail:
    summary = _summary(opp, job, db)
    return OpportunityDetail(
        **summary.model_dump(),
        description=job.description,
        fit_reasoning=opp.fit_reasoning,
        visa_reasoning=opp.visa_reasoning,
        skills_required=list(job.skills_required or []),
    )


@router.get("", response_model=OpportunityListResponse)
def get_opportunities(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    country: str | None = None,
    countries: str | None = None,
    visa_status: str | None = None,
    visa_statuses: str | None = None,
    classification: str | None = None,
    classifications: str | None = None,
    min_score: float | None = None,
    archetype: str | None = None,
    archetypes: str | None = None,
    min_salary_usd: int | None = None,
    exclude_suspicious: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
) -> OpportunityListResponse:
    """List scored opportunities with optional filters."""
    rows, total = list_opportunities(
        db,
        user,
        page=page,
        page_size=page_size,
        country=country,
        countries=countries,
        visa_status=visa_status,
        visa_statuses=visa_statuses,
        classification=classification,
        classifications=classifications,
        min_score=min_score,
        archetype=archetype,
        archetypes=archetypes,
        min_salary_usd=min_salary_usd,
        exclude_suspicious=exclude_suspicious,
        date_from=date_from,
        date_to=date_to,
    )
    return OpportunityListResponse(
        items=[_summary(opp, job, db) for opp, job in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{opportunity_id}", response_model=OpportunityDetail)
def get_opportunity(
    opportunity_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OpportunityDetail:
    """Return full opportunity detail including job description."""
    from services.opportunity_actions import _get_opportunity_for_user

    opp, job = _get_opportunity_for_user(db, user, opportunity_id)
    return _detail(opp, job, db)


@router.post("/{opportunity_id}/approve", response_model=OpportunityActionResponse)
def approve(
    opportunity_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OpportunityActionResponse:
    """Approve an opportunity: tailor resume, create application, enqueue cover letter."""
    opp, application = approve_opportunity(db, user, opportunity_id)
    background_tasks.add_task(run_cover_letter_enrichment, application.id, user.id)
    background_tasks.add_task(run_theme_extraction, application.id, user.id)
    return OpportunityActionResponse(
        id=str(opp.id),
        user_feedback=opp.user_feedback or "approved",
        application_id=str(application.id),
    )


@router.post("/{opportunity_id}/reject", response_model=OpportunityActionResponse)
def reject(
    opportunity_id: uuid.UUID,
    payload: RejectRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OpportunityActionResponse:
    """Reject an opportunity and update blacklists when applicable."""
    opp = reject_opportunity(db, user, opportunity_id, payload.reason)
    return OpportunityActionResponse(
        id=str(opp.id),
        user_feedback=opp.user_feedback or "rejected",
        reject_reason=opp.reject_reason,
    )


@router.post("/{opportunity_id}/skip", response_model=OpportunityActionResponse)
def skip(
    opportunity_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OpportunityActionResponse:
    """Mark an opportunity as skipped."""
    opp = skip_opportunity(db, user, opportunity_id)
    return OpportunityActionResponse(
        id=str(opp.id),
        user_feedback=opp.user_feedback or "skipped",
    )
