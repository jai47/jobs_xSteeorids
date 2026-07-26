"""Resume version routes."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from db.models import User
from services.resume_versions import (
    compile_version_latex,
    delete_all_resume_versions,
    delete_resume_version,
    ensure_version_latex,
    generate_resume_pdf,
    list_resume_versions,
    save_latex_source,
)

router = APIRouter(prefix="/resume-versions", tags=["resumes"])


class ResumeVersionItem(BaseModel):
    id: str
    job_id: str
    application_id: str | None = None
    job_title: str
    company: str
    ats_score_before: int | None = None
    ats_score_after: int | None = None
    keywords_added: list[str] = Field(default_factory=list)
    skill_gaps: list[str] = Field(default_factory=list)
    master_text: str = ""
    tailored_markdown: str = ""
    latex_source: str = ""
    ai_tailored: bool = False
    ai_latex: bool = False
    pdf_engine: str = "html"
    has_latex_pdf: bool = False
    created_at: Any = None


class ResumeVersionListResponse(BaseModel):
    versions: list[ResumeVersionItem]


class ResumeVersionDeleteAllResponse(BaseModel):
    deleted_count: int


@router.get("", response_model=ResumeVersionListResponse)
def get_resume_versions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ResumeVersionListResponse:
    """List tailored resume versions with master text for comparison."""
    versions = list_resume_versions(db, user)
    return ResumeVersionListResponse(versions=versions)


@router.delete("/all", response_model=ResumeVersionDeleteAllResponse)
def remove_all_resume_versions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ResumeVersionDeleteAllResponse:
    """Delete all tailored resume versions for the current user."""
    deleted_count = delete_all_resume_versions(db, user)
    return ResumeVersionDeleteAllResponse(deleted_count=deleted_count)


@router.delete("/{version_id}", status_code=204, response_class=Response)
def remove_resume_version(
    version_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Delete a tailored resume version (application row is kept)."""
    delete_resume_version(db, user, version_id)
    return Response(status_code=204)


class LatexSaveRequest(BaseModel):
    latex_source: str = Field(min_length=20)


class LatexCompileRequest(BaseModel):
    latex_source: str | None = None


class LatexEnsureRequest(BaseModel):
    force: bool = False


class LatexSourceResponse(BaseModel):
    latex_source: str


@router.put("/{version_id}/latex", response_model=LatexSourceResponse)
def save_resume_latex(
    version_id: uuid.UUID,
    payload: LatexSaveRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LatexSourceResponse:
    """Persist user-edited LaTeX source for a resume version."""
    latex = save_latex_source(db, user, version_id, payload.latex_source)
    return LatexSourceResponse(latex_source=latex)


@router.post("/{version_id}/latex/ensure", response_model=LatexSourceResponse)
def ensure_resume_latex(
    version_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    payload: LatexEnsureRequest | None = None,
) -> LatexSourceResponse:
    """Return LaTeX for a version, generating it from the one-page template if missing."""
    force = bool(payload.force) if payload else False
    latex = ensure_version_latex(db, user, version_id, force=force)
    return LatexSourceResponse(latex_source=latex)


@router.post("/{version_id}/latex/compile")
def compile_resume_latex(
    version_id: uuid.UUID,
    payload: LatexCompileRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Compile (draft) LaTeX to PDF for the live editor preview."""
    pdf_bytes = compile_version_latex(db, user, version_id, payload.latex_source)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=\"resume-preview.pdf\""},
    )


@router.get("/{version_id}/pdf")
def download_resume_pdf(
    version_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Generate and download a single-page LaTeX resume PDF on demand."""
    pdf_bytes = generate_resume_pdf(db, user, version_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume-{version_id}.pdf"'},
    )
