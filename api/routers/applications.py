"""Application tracker routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.application import ApplicationListResponse, ApplicationResponse, ApplicationUpdate
from db.models import User
from services.application_tracker import _follow_up_flags, list_applications, update_application

router = APIRouter(prefix="/applications", tags=["applications"])


def _application_response(application, job, opportunity) -> ApplicationResponse:
    first_overdue, second_overdue = _follow_up_flags(application)
    return ApplicationResponse(
        id=str(application.id),
        job_id=str(job.id),
        company=job.company,
        title=job.title,
        country=job.country,
        status=application.status or "approved",
        applied_at=application.applied_at,
        follow_up_due=application.follow_up_due,
        followed_up_at=application.followed_up_at,
        second_follow_up_due=application.second_follow_up_due,
        notes=application.notes,
        updated_at=application.updated_at,
        opportunity_id=str(opportunity.id) if opportunity else None,
        is_follow_up_overdue=first_overdue,
        is_second_follow_up_overdue=second_overdue,
    )


@router.get("", response_model=ApplicationListResponse)
def get_applications(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationListResponse:
    """Return all applications for the tracker board."""
    rows = list_applications(db, user)
    return ApplicationListResponse(
        applications=[
            _application_response(application, job, opportunity)
            for application, job, opportunity in rows
        ]
    )


@router.patch("/{application_id}", response_model=ApplicationResponse)
def patch_application(
    application_id: uuid.UUID,
    payload: ApplicationUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationResponse:
    """Update application status or notes."""
    updates = payload.model_dump(exclude_unset=True)
    application, job = update_application(db, user, application_id, **updates)
    opp = None
    from db.models import ScoredOpportunity

    opp = (
        db.query(ScoredOpportunity)
        .filter_by(job_id=job.id, user_id=user.id)
        .order_by(ScoredOpportunity.created_at.desc())
        .first()
    )
    return _application_response(application, job, opp)
