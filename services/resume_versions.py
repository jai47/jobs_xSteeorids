"""Resume version listing and PDF generation."""

from __future__ import annotations

import logging
import uuid
from io import BytesIO

import markdown
from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import Application, Job, MasterResume, ResumeVersion, User
from llm.client import LLMError
from llm.resume_latex import generate_latex_resume
from services.latex_compiler import compile_latex_to_pdf, count_pdf_pages, tectonic_available
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


def _version_dict(
    session: Session,
    version: ResumeVersion,
    master_text: str,
) -> dict:
    job = session.get(Job, version.job_id)
    application = (
        session.query(Application)
        .filter_by(user_id=version.user_id, resume_version_id=version.id)
        .first()
    )
    return {
        "id": str(version.id),
        "job_id": str(version.job_id),
        "application_id": str(application.id) if application else None,
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

    return [_version_dict(session, version, master_text) for version in versions]


def regenerate_resume_for_application(
    session: Session,
    user: User,
    application_id: uuid.UUID,
) -> dict:
    """Create a new tailored resume version for an existing application."""
    from services.llm_generation_guard import enforce_daily_generation_guard
    from services.resume_tailoring import create_tailored_resume_version, get_active_master_resume

    application = (
        session.query(Application)
        .filter_by(id=application_id, user_id=user.id)
        .first()
    )
    if application is None:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")

    enforce_daily_generation_guard(session, user.id)
    master = get_active_master_resume(session, user)
    version = create_tailored_resume_version(session, user, job, master)
    application.resume_version_id = version.id
    session.flush()
    master_text = master.raw_text or ""
    return _version_dict(session, version, master_text)


def delete_resume_version(session: Session, user: User, version_id: uuid.UUID) -> None:
    """Delete a tailored resume version and unlink any application reference."""
    version = (
        session.query(ResumeVersion)
        .filter_by(id=version_id, user_id=user.id)
        .first()
    )
    if version is None:
        raise APIError(404, "Resume version not found", "NOT_FOUND")
    session.query(Application).filter_by(user_id=user.id, resume_version_id=version.id).update(
        {Application.resume_version_id: None},
        synchronize_session=False,
    )
    session.delete(version)
    session.flush()


def delete_all_resume_versions(session: Session, user: User) -> int:
    """Delete all tailored resume versions for the user; applications are kept."""
    versions = session.query(ResumeVersion).filter_by(user_id=user.id).all()
    if not versions:
        return 0
    version_ids = [version.id for version in versions]
    session.query(Application).filter(
        Application.user_id == user.id,
        Application.resume_version_id.in_(version_ids),
    ).update({Application.resume_version_id: None}, synchronize_session=False)
    for version in versions:
        session.delete(version)
    session.flush()
    return len(version_ids)


def _fits_one_page(latex: str) -> bool | None:
    """Return True/False if page count could be verified, None if tectonic is unavailable."""
    if not tectonic_available():
        return None
    try:
        pdf_bytes = compile_latex_to_pdf(latex)
    except RuntimeError:
        return None
    return count_pdf_pages(pdf_bytes) <= 1


def _latex_compiles(latex: str) -> bool | None:
    """Return True/False if compilation could be verified, None if no engine is available."""
    if not tectonic_available():
        return None
    try:
        compile_latex_to_pdf(latex)
        return True
    except RuntimeError as exc:
        log.warning("LaTeX compile check failed: %s", str(exc)[-300:])
        return False


def _generate_one_page_latex(
    tailored: str,
    job_title: str,
    company: str,
    user_id,
    session: Session,
) -> tuple[str, bool | None]:
    """Generate template-based LaTeX via the LLM, verifying it compiles and fits
    one page. Returns the LaTeX and whether it was verified to fit one page
    (None if unverifiable — no LaTeX engine). Raises LLMError if the LLM path
    is unavailable entirely."""
    latex = generate_latex_resume(tailored, job_title, company, user_id, session)
    compiles = _latex_compiles(latex)
    if compiles is False:
        log.warning("AI LaTeX failed to compile; regenerating with compile-fix hint")
        try:
            latex = generate_latex_resume(
                tailored,
                job_title,
                company,
                user_id,
                session,
                overflow_hint=True,
            )
            # Append a stronger compile-oriented retry if still broken.
            compiles = _latex_compiles(latex)
            if compiles is False:
                raise LLMError("AI LaTeX did not compile after retry")
        except LLMError:
            raise

    fits = _fits_one_page(latex)
    if fits is not False:
        return latex, fits

    log.warning("Generated resume exceeded one page; regenerating with trim instruction")
    try:
        retry_latex = generate_latex_resume(
            tailored, job_title, company, user_id, session, overflow_hint=True
        )
    except LLMError:
        return latex, fits

    if _latex_compiles(retry_latex) is False:
        return latex, fits

    retry_fits = _fits_one_page(retry_latex)
    return (retry_latex, retry_fits) if retry_fits is not False else (latex, fits)


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
            latex, fits = _generate_one_page_latex(tailored, job_title, company, version.user_id, session)
            if fits is not False and _latex_compiles(latex) is not False:
                version.latex_source = latex
                session.flush()
                return latex
            log.warning("LLM output failed compile/page checks; using structured template")
        except LLMError:
            log.warning("LLM LaTeX generation failed; using structured template")

    latex = _build_one_page_structured_latex(tailored, job_title, company)
    # Structured fallback must also compile when an engine is present.
    if _latex_compiles(latex) is False:
        log.warning("Structured LaTeX failed compile check; returning best-effort source")
    version.latex_source = latex
    session.flush()
    return latex


def _build_one_page_structured_latex(tailored: str, job_title: str, company: str) -> str:
    """Build the deterministic template-matching LaTeX, shrinking the per-section
    line cap if the compiled PDF still overflows one page."""
    latex = build_structured_latex(tailored, job_title=job_title, company=company)
    for cap in (6, 3):
        if _fits_one_page(latex) is not False:
            return latex
        latex = build_structured_latex(
            tailored, job_title=job_title, company=company, max_lines_per_section=cap
        )
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


def _get_user_version(session: Session, user: User, version_id: uuid.UUID) -> ResumeVersion:
    version = session.get(ResumeVersion, version_id)
    if version is None or version.user_id != user.id:
        raise APIError(404, "Resume version not found", "NOT_FOUND")
    return version


def save_latex_source(
    session: Session,
    user: User,
    version_id: uuid.UUID,
    latex_source: str,
) -> str:
    """Persist user-edited LaTeX for a resume version."""
    version = _get_user_version(session, user, version_id)
    version.latex_source = latex_source
    session.flush()
    return latex_source


def ensure_version_latex(
    session: Session,
    user: User,
    version_id: uuid.UUID,
    *,
    force: bool = False,
) -> str:
    """Return the version's LaTeX, generating it from the one-page template if missing."""
    version = _get_user_version(session, user, version_id)
    job = session.get(Job, version.job_id)
    return ensure_latex_source(session, version, job, force=force)


def compile_version_latex(
    session: Session,
    user: User,
    version_id: uuid.UUID,
    latex_source: str | None = None,
) -> bytes:
    """Compile LaTeX (draft or saved) for the live preview. Raises APIError with
    the tectonic log on failure — no HTML fallback, the editor needs real errors."""
    version = _get_user_version(session, user, version_id)
    latex = (latex_source or "").strip() or (version.latex_source or "")
    if not latex:
        latex = ensure_version_latex(session, user, version_id)
    if not tectonic_available():
        raise APIError(
            503,
            "LaTeX compiler unavailable — install a LaTeX engine (tectonic, pdflatex, or xelatex)",
            "LATEX_UNAVAILABLE",
        )
    try:
        return compile_latex_to_pdf(latex)
    except RuntimeError as exc:
        raise APIError(400, "LaTeX compilation failed", "LATEX_COMPILE_ERROR", detail=str(exc)[:2000])


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
