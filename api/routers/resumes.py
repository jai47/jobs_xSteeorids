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
from services.resume_versions import generate_resume_pdf, list_resume_versions

router = APIRouter(prefix="/resume-versions", tags=["resumes"])


class ResumeVersionItem(BaseModel):
    id: str
    job_id: str
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


@router.get("", response_model=ResumeVersionListResponse)
def get_resume_versions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ResumeVersionListResponse:
    """List tailored resume versions with master text for comparison."""
    versions = list_resume_versions(db, user)
    return ResumeVersionListResponse(versions=versions)


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
