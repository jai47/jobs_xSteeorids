"""Resume version listing and PDF generation."""

from __future__ import annotations

import uuid
from io import BytesIO

import markdown
import weasyprint
from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import Job, MasterResume, ResumeVersion, User


def list_resume_versions(session: Session, user: User) -> list[dict]:
    """Return tailored resume versions with master text for side-by-side view."""
    versions = (
        session.query(ResumeVersion)
        .filter_by(user_id=user.id)
        .order_by(ResumeVersion.created_at.desc())
        .all()
    )
    master = (
        session.query(MasterResume)
        .filter_by(user_id=user.id, is_active=True)
        .order_by(MasterResume.uploaded_at.desc())
        .first()
    )
    master_text = master.raw_text if master else ""

    result: list[dict] = []
    for version in versions:
        job = session.get(Job, version.job_id)
        result.append(
            {
                "id": str(version.id),
                "job_id": str(version.job_id),
                "job_title": job.title if job else "Unknown role",
                "company": job.company if job else "Unknown company",
                "ats_score_before": version.ats_score_before,
                "ats_score_after": version.ats_score_after,
                "keywords_added": list(version.keywords_added or []),
                "skill_gaps": list(version.skill_gaps or []),
                "master_text": master_text,
                "tailored_markdown": version.tailored_markdown or "",
                "created_at": version.created_at,
            }
        )
    return result


def generate_resume_pdf(session: Session, user: User, version_id: uuid.UUID) -> bytes:
    """Generate a PDF from tailored markdown on demand."""
    version = session.get(ResumeVersion, version_id)
    if version is None or version.user_id != user.id:
        raise APIError(404, "Resume version not found", "NOT_FOUND")
    if not version.tailored_markdown:
        raise APIError(404, "No tailored content available", "NOT_FOUND")

    html = markdown.markdown(version.tailored_markdown)
    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    if pdf_bytes is None:
        raise APIError(500, "PDF generation failed", "INTERNAL_ERROR")
    return pdf_bytes
