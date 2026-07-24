"""Apply Packet: assemble resume + cover letter + LinkedIn note checklist."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.autopilot import ApplyPacketResponse, ChecklistItem
from db.models import Application, CoverLetter, Job, ResumeVersion, User
from llm.linkedin_find_network import generate_find_network_suggestions, linkedin_people_search_url
from services.autopilot.message_pack import ensure_connect_note, get_stored_message_pack
from services.autopilot.state import get_app_autopilot, patch_app_autopilot
from services.cover_letters import generate_cover_letter, get_or_create_cover_letter
from services.llm_generation_guard import enforce_daily_generation_guard


def _get_application(session: Session, user: User, application_id: uuid.UUID) -> tuple[Application, Job]:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")
    return application, job


def build_apply_packet(
    session: Session,
    user: User,
    application_id: uuid.UUID,
) -> ApplyPacketResponse:
    application, job = _get_application(session, user, application_id)
    letter = session.query(CoverLetter).filter_by(application_id=application.id).first()
    resume: ResumeVersion | None = None
    if application.resume_version_id:
        resume = session.get(ResumeVersion, application.resume_version_id)

    pack = get_stored_message_pack(application)
    connect_note = None
    if pack:
        for msg in pack.get("messages") or []:
            if isinstance(msg, dict) and msg.get("key") == "connect":
                connect_note = msg.get("body")
                break

    cache = get_app_autopilot(application)
    network_suggestions = list(cache.get("network_suggestions") or [])
    form_answers_blob = cache.get("form_answers") if isinstance(cache.get("form_answers"), dict) else {}
    form_answers = list(form_answers_blob.get("answers") or []) if form_answers_blob else []

    checklist: list[ChecklistItem] = [
        ChecklistItem(
            key="resume",
            label="Tailored resume ready",
            done=bool(resume and resume.tailored_markdown),
            href=f"/resume-versions/{resume.id}/pdf" if resume else None,
        ),
        ChecklistItem(
            key="cover_letter",
            label="Cover letter drafted",
            done=bool(letter and letter.body and letter.body.strip()),
            href=f"/applications/{application.id}/cover-letter/pdf" if letter and letter.body else None,
        ),
        ChecklistItem(
            key="connect_note",
            label="LinkedIn connect note ready",
            done=bool(connect_note),
            href=None,
        ),
        ChecklistItem(
            key="form_answers",
            label="Form answers drafted",
            done=bool(form_answers),
            href=None,
        ),
        ChecklistItem(
            key="job_link",
            label="Open job posting",
            done=bool(job.url),
            href=job.url,
        ),
    ]
    ready = all(c.done for c in checklist if c.key not in {"job_link", "form_answers"}) and bool(job.url)

    return ApplyPacketResponse(
        application_id=str(application.id),
        company=job.company,
        title=job.title,
        job_url=job.url,
        status=application.status or "approved",
        resume_version_id=str(resume.id) if resume else None,
        ats_score_before=resume.ats_score_before if resume else None,
        ats_score_after=resume.ats_score_after if resume else None,
        cover_letter_status=letter.status if letter else None,
        has_cover_letter_body=bool(letter and letter.body and letter.body.strip()),
        connect_note=connect_note,
        network_suggestions=network_suggestions,
        form_answers=form_answers,
        checklist=checklist,
        ready=ready,
    )


def ensure_apply_packet(
    session: Session,
    user: User,
    application_id: uuid.UUID,
    *,
    check_limits: bool = True,
) -> ApplyPacketResponse:
    """Fill missing cover letter + connect note + network suggestions (fail-soft pieces)."""
    application, job = _get_application(session, user, application_id)

    letter = get_or_create_cover_letter(session, user, application)
    if not (letter.body and letter.body.strip()):
        if check_limits:
            enforce_daily_generation_guard(session, user.id)
        try:
            generate_cover_letter(
                session,
                user,
                application,
                job,
                check_limits=check_limits,
                allow_generating_state=True,
            )
        except Exception:
            pass

    try:
        ensure_connect_note(session, user, application, job, check_limits=check_limits)
    except (LLMError, APIError):
        pass
    except Exception:
        pass

    cache = get_app_autopilot(application)
    if not cache.get("network_suggestions"):
        try:
            if check_limits:
                enforce_daily_generation_guard(session, user.id)
            raw = generate_find_network_suggestions(
                company=job.company,
                job_title=job.title,
                job_description=job.description,
                candidate_name=user.name,
                skills=list(user.parsed_skills or []),
                user_id=user.id,
                session=session,
            )
            suggestions = []
            for item in raw.get("suggestions") or []:
                if not isinstance(item, dict):
                    continue
                query = str(item.get("title_query") or "").strip()
                if not query:
                    continue
                suggestions.append(
                    {
                        "role_tag": item.get("role_tag") or "other",
                        "title_query": query,
                        "why": item.get("why") or "",
                        "linkedin_search_url": linkedin_people_search_url(query),
                        "priority": item.get("priority") or 3,
                    }
                )
            patch_app_autopilot(
                application,
                network_suggestions=suggestions[:6],
                network_suggestions_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            pass

    session.flush()
    return build_apply_packet(session, user, application_id)


def ensure_apply_packet_bits(application_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Background fail-soft hook after approve."""
    from db.engine import SessionLocal

    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        application = session.get(Application, application_id)
        if user is None or application is None:
            return
        ensure_apply_packet(session, user, application_id, check_limits=False)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()
