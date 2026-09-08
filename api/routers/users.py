"""User profile, resume upload, and configuration routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from api.deps import APIError, get_current_user, get_db
from api.schemas.billing import (
    UserLlmKeyUpsert,
    UserLlmKeysResponse,
    UserLlmProviderStatus,
    UserPreferredProviderUpdate,
)
from api.schemas.user import (
    BlacklistResponse,
    BlacklistUpdate,
    LLMProviderUpdate,
    LLMStatusResponse,
    ResumeTextUpload,
    ResumeUploadResponse,
    UserProfileResponse,
    UserProfileUpdate,
)
from llm.providers import build_status_payload
from services.llm_runtime_config import VALID_PROVIDERS, set_selected_provider
from db.models import User
from services.cover_letters import get_user_angles
from services.onboarding import save_master_resume_text, upload_master_resume, user_has_active_resume
from services.user_llm_keys import delete_user_key, list_user_keys, upsert_user_key

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
        is_admin=bool(getattr(user, "is_admin", False)),
        token_balance=int(getattr(user, "token_balance", 1000) or 0),
        preferred_llm_provider=getattr(user, "preferred_llm_provider", None) or "auto",
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
    """Deprecated for end users — platform .env status. Prefer /admin/llm-platform-status."""
    return LLMStatusResponse(**build_status_payload())


@router.patch("/config/llm-provider", response_model=LLMStatusResponse)
def update_llm_provider(
    payload: LLMProviderUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LLMStatusResponse:
    """Set the preferred LLM provider for this user (BYOK / platform fallback)."""
    provider = payload.provider.strip().lower()
    if provider not in VALID_PROVIDERS:
        raise APIError(
            400,
            f"Unknown provider '{payload.provider}'. "
            f"Choose one of: {', '.join(sorted(VALID_PROVIDERS))}.",
        )
    user.preferred_llm_provider = provider
    # Admins can still set the deployment-wide default for unauthenticated tooling.
    if bool(getattr(user, "is_admin", False)):
        set_selected_provider(provider)
    db.flush()
    payload_out = build_status_payload()
    payload_out["selected_provider"] = provider
    for key in list(payload_out.keys()):
        if key.endswith("_configured"):
            payload_out[key] = False
    return LLMStatusResponse(**payload_out)


@router.get("/users/me/llm-keys", response_model=UserLlmKeysResponse)
def get_my_llm_keys(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserLlmKeysResponse:
    providers = [UserLlmProviderStatus(**row) for row in list_user_keys(db, user)]
    return UserLlmKeysResponse(
        preferred_provider=getattr(user, "preferred_llm_provider", None) or "auto",
        providers=providers,
    )


@router.put("/users/me/llm-keys", response_model=UserLlmKeysResponse)
def put_my_llm_key(
    payload: UserLlmKeyUpsert,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserLlmKeysResponse:
    upsert_user_key(db, user, payload.provider, payload.api_key, model=payload.model)
    providers = [UserLlmProviderStatus(**row) for row in list_user_keys(db, user)]
    return UserLlmKeysResponse(
        preferred_provider=getattr(user, "preferred_llm_provider", None) or "auto",
        providers=providers,
    )


@router.delete("/users/me/llm-keys/{provider}", response_model=UserLlmKeysResponse)
def delete_my_llm_key(
    provider: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserLlmKeysResponse:
    delete_user_key(db, user, provider)
    providers = [UserLlmProviderStatus(**row) for row in list_user_keys(db, user)]
    return UserLlmKeysResponse(
        preferred_provider=getattr(user, "preferred_llm_provider", None) or "auto",
        providers=providers,
    )


@router.patch("/users/me/llm-preference", response_model=UserLlmKeysResponse)
def patch_llm_preference(
    payload: UserPreferredProviderUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserLlmKeysResponse:
    provider = payload.provider.strip().lower()
    if provider not in VALID_PROVIDERS:
        raise APIError(400, f"Unknown provider '{payload.provider}'", "INVALID_PROVIDER")
    user.preferred_llm_provider = provider
    db.flush()
    providers = [UserLlmProviderStatus(**row) for row in list_user_keys(db, user)]
    return UserLlmKeysResponse(preferred_provider=provider, providers=providers)


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
