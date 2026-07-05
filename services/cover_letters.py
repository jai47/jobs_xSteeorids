"""Cover letter persistence, state machine, and generation."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from db.models import Application, CoverLetter, Job, MasterResume, ResumeVersion, User
from llm.cover_letter import generate_cover_letter_text
from services.llm_generation_guard import enforce_daily_generation_guard

log = logging.getLogger(__name__)

VALID_STATUSES = frozenset({"pending", "generating", "draft", "approved", "failed"})
MAX_WORDS_HARD = 320
MAX_WORDS_TARGET = 300
MAX_BODY_CHARS = 5000
PER_JOB_DAILY_REGENERATIONS = 3

DEFAULT_ANGLES: dict[str, str] = {
    "why_company": "Explain genuine interest in the company mission and recent work.",
    "problem_i_solve": "Describe the problem this role addresses and how your experience maps to it.",
    "my_approach": "Highlight your approach to delivering results in similar contexts.",
    "tone": "Professional, concise, and confident — never arrogant.",
}


def word_count(text: str | None) -> int:
    if not text:
        return 0
    return len(text.split())


def _truncate_at_paragraph(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    truncated: list[str] = []
    for paragraph in text.split("\n\n"):
        chunk = paragraph.split()
        if len(truncated) + len(chunk) <= max_words:
            truncated.extend(chunk)
            truncated.append("\n\n")
        else:
            remaining = max_words - len(truncated)
            if remaining > 0:
                truncated.extend(chunk[:remaining])
            break
    return " ".join(w for w in truncated if w != "\n\n").strip()


def enforce_word_limit(text: str, user_id: uuid.UUID, session: Session) -> str:
    """>320 words: one shorten retry via LLM, then hard truncate."""
    if word_count(text) <= MAX_WORDS_HARD:
        return text
    try:
        from llm.client import call_llm

        shortened = call_llm(
            f"Shorten this cover letter to at most {MAX_WORDS_TARGET} words. "
            f"Keep facts unchanged. Return plain text only.\n\n{text}",
            "cover_letter",
            user_id,
            session,
            max_tokens=1200,
        )
        if word_count(shortened) <= MAX_WORDS_HARD:
            return shortened.strip()
    except LLMError:
        pass
    return _truncate_at_paragraph(text, MAX_WORDS_HARD)


def get_user_angles(user: User) -> dict[str, str]:
    angles = user.cover_letter_angles if isinstance(user.cover_letter_angles, dict) else {}
    return {**DEFAULT_ANGLES, **angles}


def get_cover_letter_for_application(
    session: Session,
    user: User,
    application_id: uuid.UUID,
) -> CoverLetter:
    letter = (
        session.query(CoverLetter)
        .filter_by(application_id=application_id, user_id=user.id)
        .first()
    )
    if letter is None:
        raise APIError(404, "Cover letter not found", "NOT_FOUND")
    return letter


def get_or_create_cover_letter(
    session: Session,
    user: User,
    application: Application,
) -> CoverLetter:
    letter = (
        session.query(CoverLetter)
        .filter_by(application_id=application.id, user_id=user.id)
        .first()
    )
    if letter is None:
        letter = CoverLetter(
            application_id=application.id,
            user_id=user.id,
            status="pending",
        )
        session.add(letter)
        session.flush()
    return letter


def _resume_text_for_application(session: Session, application: Application, user: User) -> str:
    if application.resume_version_id:
        version = session.get(ResumeVersion, application.resume_version_id)
        if version and version.tailored_markdown:
            return version.tailored_markdown
    master = (
        session.query(MasterResume)
        .filter_by(user_id=user.id, is_active=True)
        .order_by(MasterResume.uploaded_at.desc())
        .first()
    )
    if master and master.raw_text:
        return master.raw_text
    raise APIError(
        422,
        "Upload a resume before generating a cover letter",
        "VALIDATION_ERROR",
    )


def _check_per_job_regeneration_limit(letter: CoverLetter) -> None:
    # 1 initial + 3 regenerations = 4 total generations max.
    if (letter.generation_count or 0) >= PER_JOB_DAILY_REGENERATIONS + 1:
        raise APIError(
            429,
            "Maximum regenerations for this job today",
            "RATE_LIMITED",
            retry_after_seconds=3600,
        )


def generate_cover_letter(
    session: Session,
    user: User,
    application: Application,
    job: Job,
    *,
    check_limits: bool = True,
    allow_generating_state: bool = False,
) -> CoverLetter:
    """Generate or regenerate cover letter body (synchronous)."""
    letter = get_or_create_cover_letter(session, user, application)
    if letter.status == "generating" and not allow_generating_state:
        raise APIError(409, "Cover letter generation in progress", "GENERATION_IN_PROGRESS")
    if check_limits:
        enforce_daily_generation_guard(session, user.id)
        if letter.generation_count > 0:
            _check_per_job_regeneration_limit(letter)

    angles = get_user_angles(user)
    letter.status = "generating"
    letter.last_error = None
    letter.angles_snapshot = angles
    letter.updated_at = datetime.now(timezone.utc)
    session.flush()

    try:
        resume_text = _resume_text_for_application(session, application, user)
        body = generate_cover_letter_text(
            job_title=job.title,
            company=job.company,
            job_description=job.description or "",
            resume_text=resume_text,
            angles=angles,
            user_id=user.id,
            session=session,
        )
        body = enforce_word_limit(body, user.id, session)
        letter.body = body
        letter.status = "draft"
        letter.generation_count = (letter.generation_count or 0) + 1
        from services.notifications.producers import enqueue_cover_letter_ready

        enqueue_cover_letter_ready(session, user, application, job.company, job.title)
    except LLMError as exc:
        letter.status = "failed"
        letter.last_error = str(exc)
        log.warning("Cover letter generation failed for application %s: %s", application.id, exc)
    except Exception as exc:
        letter.status = "failed"
        letter.last_error = str(exc)
        log.exception("Cover letter generation error")
    letter.updated_at = datetime.now(timezone.utc)
    session.flush()
    return letter


def update_cover_letter_body(
    session: Session,
    user: User,
    application_id: uuid.UUID,
    body: str,
) -> CoverLetter:
    if len(body) > MAX_BODY_CHARS:
        raise APIError(422, "Cover letter body too long", "VALIDATION_ERROR")
    letter = get_cover_letter_for_application(session, user, application_id)
    if letter.status == "generating":
        raise APIError(409, "Cover letter generation in progress", "GENERATION_IN_PROGRESS")
    letter.body = body
    if letter.status == "approved":
        letter.status = "draft"
    letter.updated_at = datetime.now(timezone.utc)
    session.flush()
    return letter


def approve_cover_letter(
    session: Session,
    user: User,
    application_id: uuid.UUID,
) -> CoverLetter:
    letter = get_cover_letter_for_application(session, user, application_id)
    if letter.status == "generating":
        raise APIError(409, "Cover letter generation in progress", "GENERATION_IN_PROGRESS")
    if letter.status == "failed":
        raise APIError(409, "Cover letter generation failed — retry first", "GENERATION_IN_PROGRESS")
    if not letter.body:
        raise APIError(422, "Cover letter body is empty", "VALIDATION_ERROR")
    letter.status = "approved"
    letter.updated_at = datetime.now(timezone.utc)
    session.flush()
    return letter


def to_response_dict(letter: CoverLetter) -> dict:
    return {
        "id": str(letter.id),
        "application_id": str(letter.application_id),
        "status": letter.status,
        "body": letter.body,
        "word_count": word_count(letter.body),
        "generation_count": letter.generation_count or 0,
        "error": letter.last_error,
        "created_at": letter.created_at,
        "updated_at": letter.updated_at,
    }
