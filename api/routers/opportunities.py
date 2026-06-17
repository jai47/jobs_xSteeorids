"""Scored opportunity routes."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.opportunity import (
    OpportunityActionResponse,
    OpportunityDetail,
    OpportunityListResponse,
    OpportunitySummary,
    RejectRequest,
)
from db.models import Job, ScoredOpportunity, User
from services.opportunity_actions import (
    approve_opportunity,
    list_opportunities,
    reject_opportunity,
    skip_opportunity,
)

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


def _summary(opp: ScoredOpportunity, job: Job) -> OpportunitySummary:
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
        user_feedback=opp.user_feedback,
        digest_date=opp.digest_date,
        created_at=opp.created_at,
        url=job.url,
        is_stale=bool(job.is_stale),
    )


def _detail(opp: ScoredOpportunity, job: Job) -> OpportunityDetail:
    summary = _summary(opp, job)
    return OpportunityDetail(
        **summary.model_dump(),
        description=job.description,
        fit_reasoning=opp.fit_reasoning,
        visa_reasoning=opp.visa_reasoning,
        score_skill_match=opp.score_skill_match,
        score_role_match=opp.score_role_match,
        score_experience=opp.score_experience,
        score_country_pref=opp.score_country_pref,
        score_remote_pref=opp.score_remote_pref,
        score_fit=opp.score_fit,
        skills_required=list(job.skills_required or []),
    )


@router.get("", response_model=OpportunityListResponse)
def get_opportunities(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    country: str | None = None,
    visa_status: str | None = None,
    classification: str | None = None,
    min_score: float | None = None,
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
        visa_status=visa_status,
        classification=classification,
        min_score=min_score,
        date_from=date_from,
        date_to=date_to,
    )
    return OpportunityListResponse(
        items=[_summary(opp, job) for opp, job in rows],
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
    return _detail(opp, job)


@router.post("/{opportunity_id}/approve", response_model=OpportunityActionResponse)
def approve(
    opportunity_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OpportunityActionResponse:
    """Approve an opportunity: tailor resume, create application."""
    opp, application = approve_opportunity(db, user, opportunity_id)
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
