"""Cover letter routes under /applications/{application_id}/cover-letter."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from api.deps import APIError, get_current_user, get_db
from api.schemas.cover_letter import (
    CoverLetterGenerateResponse,
    CoverLetterResponse,
    CoverLetterUpdate,
)
from db.models import Application, CoverLetter, Job, User
from services.approval_enrichment import run_cover_letter_enrichment
from services.llm_generation_guard import enforce_daily_generation_guard
from services.cover_letters import (
    approve_cover_letter,
    get_cover_letter_for_application,
    get_or_create_cover_letter,
    to_response_dict,
    update_cover_letter_body,
    _check_per_job_regeneration_limit,
)
from services.latex_compiler import compile_latex_to_pdf, tectonic_available
from services.latex_letter import build_letter_latex

router = APIRouter(prefix="/applications", tags=["cover-letters"])


def _load_application(
    db: Session,
    user: User,
    application_id: uuid.UUID,
) -> tuple[Application, Job]:
    application = (
        db.query(Application)
        .filter_by(id=application_id, user_id=user.id)
        .first()
    )
    if application is None:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = db.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")
    return application, job


@router.get("/{application_id}/cover-letter", response_model=CoverLetterResponse)
def get_cover_letter(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CoverLetterResponse:
    _load_application(db, user, application_id)
    letter = get_cover_letter_for_application(db, user, application_id)
    return CoverLetterResponse(**to_response_dict(letter))


@router.post(
    "/{application_id}/cover-letter",
    response_model=CoverLetterGenerateResponse,
    status_code=202,
)
def post_generate_cover_letter(
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CoverLetterGenerateResponse:
    application, _job = _load_application(db, user, application_id)
    letter = get_or_create_cover_letter(db, user, application)
    if letter.status == "generating":
        raise APIError(409, "Cover letter generation in progress", "GENERATION_IN_PROGRESS")
    enforce_daily_generation_guard(db, user.id)
    if (letter.generation_count or 0) > 0:
        _check_per_job_regeneration_limit(letter)
    letter.status = "generating"
    letter.last_error = None
    db.flush()
    background_tasks.add_task(run_cover_letter_enrichment, application.id, user.id)
    return CoverLetterGenerateResponse(status="generating")


@router.put("/{application_id}/cover-letter", response_model=CoverLetterResponse)
def put_cover_letter(
    application_id: uuid.UUID,
    payload: CoverLetterUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CoverLetterResponse:
    _load_application(db, user, application_id)
    letter = update_cover_letter_body(db, user, application_id, payload.body)
    return CoverLetterResponse(**to_response_dict(letter))


@router.post("/{application_id}/cover-letter/approve", response_model=CoverLetterResponse)
def post_approve_cover_letter(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CoverLetterResponse:
    _load_application(db, user, application_id)
    letter = approve_cover_letter(db, user, application_id)
    return CoverLetterResponse(**to_response_dict(letter))


@router.get("/{application_id}/cover-letter/pdf")
def get_cover_letter_pdf(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    application, job = _load_application(db, user, application_id)
    letter = get_cover_letter_for_application(db, user, application_id)
    if letter.status != "approved":
        raise APIError(409, "Cover letter must be approved before PDF export", "GENERATION_IN_PROGRESS")
    if not letter.body:
        raise APIError(422, "Cover letter body is empty", "VALIDATION_ERROR")
    if not tectonic_available():
        raise APIError(502, "PDF engine not available", "LATEX_ERROR")
    latex = build_letter_latex(
        applicant_name=user.name,
        company=job.company,
        job_title=job.title,
        body=letter.body,
    )
    try:
        pdf_bytes = compile_latex_to_pdf(latex)
    except RuntimeError as exc:
        raise APIError(502, str(exc), "LATEX_ERROR") from exc
    filename = f"cover-letter-{job.company.replace(' ', '-')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
