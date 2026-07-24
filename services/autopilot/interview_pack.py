"""Interview pack: themes/stories + mock questions + thank-you."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.autopilot import InterviewPackResponse, MockQuestion
from db.models import Application, Job, User
from llm.interview_mock import generate_mock_interview
from services.autopilot.state import get_app_autopilot, patch_app_autopilot
from services.interview_prep import interview_prep
from services.llm_generation_guard import enforce_daily_generation_guard


def get_interview_pack(
    session: Session,
    user: User,
    application_id: uuid.UUID,
) -> InterviewPackResponse | None:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")
    cache = get_app_autopilot(application)
    pack = cache.get("interview_pack")
    if not isinstance(pack, dict):
        return None
    return _to_response(application, job, pack)


def _fallback_questions(themes: list[str], title: str) -> list[dict]:
    base = [
        {
            "question": f"Tell me about a project most relevant to the {title} role.",
            "tip": "Use STAR; quantify impact.",
            "related_theme": themes[0] if themes else None,
        },
        {
            "question": "Describe a time you disagreed with a teammate and how you resolved it.",
            "tip": "Show collaboration and judgment.",
            "related_theme": "conflict",
        },
        {
            "question": "What would you do in your first 90 days in this role?",
            "tip": "Tie to JD priorities; stay realistic.",
            "related_theme": themes[1] if len(themes) > 1 else None,
        },
    ]
    return base


def _to_response(application: Application, job: Job, pack: dict) -> InterviewPackResponse:
    generated_at = None
    raw_at = pack.get("generated_at")
    if isinstance(raw_at, str):
        try:
            generated_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        except ValueError:
            pass
    questions = [
        MockQuestion(
            question=str(q.get("question") or ""),
            tip=q.get("tip"),
            related_theme=q.get("related_theme"),
        )
        for q in (pack.get("mock_questions") or [])
        if isinstance(q, dict) and q.get("question")
    ]
    return InterviewPackResponse(
        application_id=str(application.id),
        company=job.company,
        title=job.title,
        themes=list(pack.get("themes") or []),
        stories=list(pack.get("stories") or []),
        uncovered_themes=list(pack.get("uncovered_themes") or []),
        mock_questions=questions,
        thank_you_note=pack.get("thank_you_note"),
        generated_at=generated_at,
    )


def generate_and_store_interview_pack(
    session: Session,
    user: User,
    application_id: uuid.UUID,
    *,
    check_limits: bool = True,
) -> InterviewPackResponse:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")

    prep = interview_prep(session, user, application_id)
    themes = prep["themes"]
    stories = prep["stories"]
    uncovered = prep["uncovered_themes"]

    if check_limits:
        enforce_daily_generation_guard(session, user.id)

    mock_questions = _fallback_questions(themes, job.title)
    thank_you = (
        f"Thank you for speaking with me about the {job.title} role at {job.company}. "
        f"I appreciated the conversation and remain very interested.\n\nBest,\n{user.name}"
    )
    try:
        raw = generate_mock_interview(
            company=job.company,
            job_title=job.title,
            job_description=job.description,
            themes=themes,
            candidate_name=user.name,
            user_id=user.id,
            session=session,
        )
        qs = []
        for item in raw.get("questions") or []:
            if isinstance(item, dict) and item.get("question"):
                qs.append(
                    {
                        "question": str(item["question"]),
                        "tip": item.get("tip"),
                        "related_theme": item.get("related_theme"),
                    }
                )
        if qs:
            mock_questions = qs[:8]
        if raw.get("thank_you_note"):
            thank_you = str(raw["thank_you_note"]).strip()
    except (LLMError, Exception):
        pass

    pack = {
        "themes": themes,
        "stories": stories,
        "uncovered_themes": uncovered,
        "mock_questions": mock_questions,
        "thank_you_note": thank_you,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    patch_app_autopilot(application, interview_pack=pack)
    session.flush()
    return _to_response(application, job, pack)


def ensure_interview_pack_background(application_id: uuid.UUID, user_id: uuid.UUID) -> None:
    from db.engine import SessionLocal

    session = SessionLocal()
    try:
        user = session.get(User, user_id)
        if user is None:
            return
        generate_and_store_interview_pack(session, user, application_id, check_limits=False)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()
