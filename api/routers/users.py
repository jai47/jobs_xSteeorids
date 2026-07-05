"""User profile, resume upload, and configuration routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from api.deps import APIError, get_current_user, get_db
from api.schemas.user import (
    BlacklistResponse,
    BlacklistUpdate,
    LLMStatusResponse,
    ResumeTextUpload,
    ResumeUploadResponse,
    UserProfileResponse,
    UserProfileUpdate,
)
from config import settings
from db.models import User
from services.cover_letters import get_user_angles
from services.onboarding import save_master_resume_text, upload_master_resume, user_has_active_resume

router = APIRouter(tags=["users"])


def _profile_response(user: User, has_active_resume: bool) -> UserProfileResponse:
    return UserProfileResponse(
        id=str(user.id),
        name=user.name,
        email=user.email,
        nationality=user.nationality,
        preferred_countries=list(user.preferred_countries or []),
        preferred_roles=list(user.preferred_roles or []),
        prefers_remote=bool(user.prefers_remote),
        salary_range_min=user.salary_range_min,
        salary_range_max=user.salary_range_max,
        salary_currency=user.salary_currency or "USD",
        years_experience=user.years_experience,
        parsed_skills=list(user.parsed_skills or []),
        has_active_resume=has_active_resume,
        score_warning_threshold=user.score_warning_threshold or 40,
        cover_letter_angles=get_user_angles(user),
        notify_digest_email=bool(user.notify_digest_email),
        notify_followup_email=bool(user.notify_followup_email),
    )


@router.get("/users/me", response_model=UserProfileResponse)
def get_profile(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserProfileResponse:
    """Return the authenticated user's profile and onboarding state."""
    return _profile_response(user, user_has_active_resume(db, user.id))


@router.patch("/users/me", response_model=UserProfileResponse)
def update_profile(
    payload: UserProfileUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserProfileResponse:
    """Update user preferences from onboarding."""
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)
    db.flush()
    return _profile_response(user, user_has_active_resume(db, user.id))


@router.post("/users/me/resume", response_model=ResumeUploadResponse)
async def upload_resume(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
) -> ResumeUploadResponse:
    """Upload a master resume, extract text, and parse skills with the LLM."""
    if not file.filename:
        raise APIError(422, "Filename is required", "VALIDATION_ERROR")

    content = await file.read()
    if not content:
        raise APIError(422, "Uploaded file is empty", "VALIDATION_ERROR")

    try:
        master_resume, parsed = upload_master_resume(db, user, file.filename, content)
    except ValueError as exc:
        raise APIError(422, str(exc), "VALIDATION_ERROR") from exc

    return ResumeUploadResponse(
        master_resume_id=str(master_resume.id),
        filename=master_resume.filename or file.filename,
        skills=parsed.skills,
        experience_years=parsed.experience_years,
        previous_titles=parsed.previous_titles,
        education=parsed.education,
        languages=parsed.languages,
    )


@router.post("/users/me/resume/text", response_model=ResumeUploadResponse)
def upload_resume_text(
    payload: ResumeTextUpload,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ResumeUploadResponse:
    """Parse pasted resume text with the LLM (bypasses browser file upload)."""
    try:
        master_resume, parsed = save_master_resume_text(db, user, payload.text)
    except ValueError as exc:
        raise APIError(422, str(exc), "VALIDATION_ERROR") from exc

    return ResumeUploadResponse(
        master_resume_id=str(master_resume.id),
        filename=master_resume.filename or "resume.txt",
        skills=parsed.skills,
        experience_years=parsed.experience_years,
        previous_titles=parsed.previous_titles,
        education=parsed.education,
        languages=parsed.languages,
    )


@router.get("/config/llm-status", response_model=LLMStatusResponse)
def llm_status() -> LLMStatusResponse:
    """Report whether LLM API keys are configured (values are never returned)."""
    return LLMStatusResponse(
        anthropic_configured=bool(settings.anthropic_api_key),
        openai_configured=bool(settings.openai_api_key),
        opencode_configured=bool(settings.opencode_api_key),
        opencode_model=settings.opencode_model if settings.opencode_api_key else None,
        local_llm_configured=bool(settings.local_llm_base_url),
        local_llm_model=settings.local_llm_model if settings.local_llm_base_url else None,
        resume_parser_mode=settings.resume_parser_mode,
    )


@router.get("/users/me/blacklists", response_model=BlacklistResponse)
def get_blacklists(
    user: Annotated[User, Depends(get_current_user)],
) -> BlacklistResponse:
    """Return the user's company, role, and location blacklists."""
    return BlacklistResponse(
        blacklisted_companies=list(user.blacklisted_companies or []),
        blacklisted_roles=list(user.blacklisted_roles or []),
        blacklisted_locations=list(user.blacklisted_locations or []),
    )


@router.patch("/users/me/blacklists", response_model=BlacklistResponse)
def update_blacklists(
    payload: BlacklistUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BlacklistResponse:
    """Replace blacklist fields provided in the request."""
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)
    db.flush()
    return BlacklistResponse(
        blacklisted_companies=list(user.blacklisted_companies or []),
        blacklisted_roles=list(user.blacklisted_roles or []),
        blacklisted_locations=list(user.blacklisted_locations or []),
    )
