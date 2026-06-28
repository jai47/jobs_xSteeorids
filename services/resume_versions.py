"""Resume version listing and PDF generation."""

from __future__ import annotations

import logging
import uuid
from io import BytesIO

import markdown
from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import Job, MasterResume, ResumeVersion, User
from llm.client import LLMError
from llm.resume_latex import generate_latex_resume
from services.latex_compiler import compile_latex_to_pdf, tectonic_available
from services.resume_formatter import build_structured_latex

log = logging.getLogger(__name__)

PDF_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: Helvetica, Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.45;
    margin: 36pt;
    color: #111;
  }}
  h1, h2, h3 {{
    color: #222;
    margin-top: 1.2em;
  }}
  ul, ol {{
    margin-left: 1.2em;
  }}
  p {{
    margin: 0.5em 0;
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def _ai_tailored(version: ResumeVersion) -> bool:
    gaps = version.skill_gaps or []
    return not any(
        "LLM not configured" in (gap or "") or "LLM tailoring unavailable" in (gap or "")
        for gap in gaps
    )


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
                "ai_tailored": _ai_tailored(version),
                "ai_latex": _ai_tailored(version) and bool(version.latex_source),
                "pdf_engine": "latex" if tectonic_available() else "html",
                "master_text": master_text,
                "tailored_markdown": version.tailored_markdown or "",
                "latex_source": version.latex_source or "",
                "has_latex_pdf": bool(version.latex_source) and tectonic_available(),
                "created_at": version.created_at,
            }
        )
    return result


def ensure_latex_source(
    session: Session,
    version: ResumeVersion,
    job: Job | None,
    *,
    force: bool = False,
) -> str:
    """Generate and cache LaTeX source for a resume version if missing."""
    if version.latex_source and not force:
        return version.latex_source

    job_title = job.title if job else "Role"
    company = job.company if job else "Company"
    tailored = version.tailored_markdown or ""
    ai_ok = _ai_tailored(version)

    if ai_ok:
        try:
            latex = generate_latex_resume(
                tailored,
                job_title,
                company,
                version.user_id,
                session,
            )
            version.latex_source = latex
            session.flush()
            return latex
        except LLMError:
            log.warning("LLM LaTeX generation failed; using structured template")

    latex = build_structured_latex(
        tailored,
        job_title=job_title,
        company=company,
    )
    version.latex_source = latex
    session.flush()
    return latex


def _markdown_to_html(tailored_markdown: str) -> str:
    body = markdown.markdown(tailored_markdown, extensions=["extra", "nl2br"])
    return PDF_HTML_TEMPLATE.format(body=body)


def _render_pdf_with_weasyprint(html: str) -> bytes | None:
    try:
        import weasyprint
    except (ImportError, OSError):
        return None

    pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    return pdf_bytes if pdf_bytes else None


def _render_pdf_with_xhtml2pdf(html: str) -> bytes:
    from xhtml2pdf import pisa

    buffer = BytesIO()
    status = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
    if status.err:
        raise APIError(500, "PDF generation failed", "INTERNAL_ERROR")
    pdf_bytes = buffer.getvalue()
    if not pdf_bytes:
        raise APIError(500, "PDF generation failed", "INTERNAL_ERROR")
    return pdf_bytes


def _render_pdf_from_markdown(tailored_markdown: str) -> bytes:
    html = _markdown_to_html(tailored_markdown)
    pdf_bytes = _render_pdf_with_weasyprint(html)
    if pdf_bytes is None:
        pdf_bytes = _render_pdf_with_xhtml2pdf(html)
    return pdf_bytes


def generate_resume_pdf(session: Session, user: User, version_id: uuid.UUID) -> bytes:
    """Generate a single-page PDF via LaTeX (AI + tectonic), with markdown fallback."""
    version = session.get(ResumeVersion, version_id)
    if version is None or version.user_id != user.id:
        raise APIError(404, "Resume version not found", "NOT_FOUND")
    if not version.tailored_markdown:
        raise APIError(404, "No tailored content available", "NOT_FOUND")

    job = session.get(Job, version.job_id)
    force_latex = not _ai_tailored(version)
    latex = ensure_latex_source(session, version, job, force=force_latex)

    if tectonic_available():
        try:
            return compile_latex_to_pdf(latex)
        except RuntimeError as exc:
            log.warning("LaTeX PDF compile failed, falling back to HTML: %s", exc)

    return _render_pdf_from_markdown(version.tailored_markdown)
