"""Application tracker routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from api.deps import APIError, get_current_user, get_db
from api.schemas.application import ApplicationListResponse, ApplicationResponse, ApplicationUpdate
from api.schemas.notification import FollowUpDraftResponse
from api.schemas.story import InterviewPrepResponse, StoryResponse, ThemesResponse, TimelineResponse, StageEventResponse
from db.models import Application, CoverLetter, Job, ScoredOpportunity, User
from services.application_tracker import (
    _follow_up_flags,
    delete_application,
    list_applications,
    update_application,
)
from services.approval_enrichment import run_theme_extraction
from services.follow_up_draft import days_since_applied, personalise_follow_up_draft, render_follow_up_draft
from services.interview_prep import interview_prep
from services.resume_versions import regenerate_resume_for_application
from services.stage_events import list_timeline_events, time_in_stage_days
from services.theme_extraction import get_themes_for_application
from api.routers.resumes import ResumeVersionItem

router = APIRouter(prefix="/applications", tags=["applications"])


def _application_response(application, job, opportunity, db: Session) -> ApplicationResponse:
    first_overdue, second_overdue = _follow_up_flags(application)
    letter = (
        db.query(CoverLetter)
        .filter_by(application_id=application.id)
        .first()
    )
    return ApplicationResponse(
        id=str(application.id),
        job_id=str(job.id),
        company=job.company,
        title=job.title,
        country=job.country,
        status=application.status or "approved",
        sub_status=application.sub_status,
        time_in_stage_days=time_in_stage_days(db, application.id),
        applied_at=application.applied_at,
        follow_up_due=application.follow_up_due,
        followed_up_at=application.followed_up_at,
        second_follow_up_due=application.second_follow_up_due,
        notes=application.notes,
        updated_at=application.updated_at,
        opportunity_id=str(opportunity.id) if opportunity else None,
        resume_version_id=str(application.resume_version_id) if application.resume_version_id else None,
        is_follow_up_overdue=first_overdue,
        is_second_follow_up_overdue=second_overdue,
        cover_letter_status=letter.status if letter else None,
        overall_score=opportunity.overall_score if opportunity else None,
        score_skill_match=opportunity.score_skill_match if opportunity else None,
        score_role_match=opportunity.score_role_match if opportunity else None,
        score_experience=opportunity.score_experience if opportunity else None,
        score_country_pref=opportunity.score_country_pref if opportunity else None,
        score_remote_pref=opportunity.score_remote_pref if opportunity else None,
        score_fit=opportunity.score_fit if opportunity else None,
        score_visa=opportunity.score_visa if opportunity else None,
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
            _application_response(application, job, opportunity, db)
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
    """Update application status, substage, or notes."""
    updates = payload.model_dump(exclude_unset=True)
    if "sub_status" in updates:
        sub_status = updates.pop("sub_status")
        application, job = update_application(db, user, application_id, sub_status=sub_status, **updates)
    else:
        application, job = update_application(db, user, application_id, **updates)
    opp = (
        db.query(ScoredOpportunity)
        .filter_by(job_id=job.id, user_id=user.id)
        .order_by(ScoredOpportunity.created_at.desc())
        .first()
    )
    return _application_response(application, job, opp, db)


@router.delete("/{application_id}", status_code=204, response_class=Response)
def remove_application(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Remove an application from the tracker."""
    delete_application(db, user, application_id)
    return Response(status_code=204)


@router.post("/{application_id}/resume/regenerate", response_model=ResumeVersionItem)
def regenerate_application_resume(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ResumeVersionItem:
    """Regenerate the tailored resume for an approved application."""
    item = regenerate_resume_for_application(db, user, application_id)
    return ResumeVersionItem(**item)


@router.get("/{application_id}/timeline", response_model=TimelineResponse)
def get_timeline(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TimelineResponse:
    application = db.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    events = list_timeline_events(db, application_id)
    return TimelineResponse(
        events=[
            StageEventResponse(
                from_status=e.from_status,
                to_status=e.to_status,
                from_sub=e.from_sub,
                to_sub=e.to_sub,
                occurred_at=e.occurred_at,
            )
            for e in events
        ]
    )


@router.get("/{application_id}/themes", response_model=ThemesResponse)
def get_themes(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ThemesResponse:
    application = db.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    row = get_themes_for_application(db, application_id)
    if row is None:
        return ThemesResponse(themes=[], status="pending")
    return ThemesResponse(themes=list(row.themes or []), status=row.status)


@router.post("/{application_id}/themes/retry", status_code=202)
def retry_themes(
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    application = db.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    background_tasks.add_task(run_theme_extraction, application.id, user.id)
    return {"status": "pending"}


@router.get("/{application_id}/interview-prep", response_model=InterviewPrepResponse)
def get_interview_prep(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterviewPrepResponse:
    data = interview_prep(db, user, application_id)
    return InterviewPrepResponse(
        themes=data["themes"],
        stories=[StoryResponse(**s) for s in data["stories"]],
        uncovered_themes=data["uncovered_themes"],
    )


@router.get("/{application_id}/follow-up-draft", response_model=FollowUpDraftResponse)
def get_follow_up_draft(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FollowUpDraftResponse:
    application = db.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = db.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")
    days = days_since_applied(application) or 0
    return FollowUpDraftResponse(
        body=render_follow_up_draft(application, job, user),
        days_since_applied=days,
        personalised=False,
    )


@router.post("/{application_id}/follow-up-draft/personalise", response_model=FollowUpDraftResponse)
def personalise_follow_up(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FollowUpDraftResponse:
    application = db.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = db.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")
    body = personalise_follow_up_draft(db, user, application, job)
    days = days_since_applied(application) or 0
    return FollowUpDraftResponse(
        body=body,
        days_since_applied=days,
        personalised=True,
    )
