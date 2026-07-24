"""Draft answers for open-ended application form questions (copy-only)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.autopilot import (
    FormAnswerItem,
    FormAnswersRequest,
    FormAnswersResponse,
)
from db.models import Application, Job, MasterResume, User
from llm.form_answers import generate_form_answers
from services.autopilot.state import get_app_autopilot, patch_app_autopilot
from services.llm_generation_guard import enforce_daily_generation_guard


def _optional_master(session: Session, user: User) -> MasterResume | None:
    return (
        session.query(MasterResume)
        .filter_by(user_id=user.id, is_active=True)
        .order_by(MasterResume.uploaded_at.desc())
        .first()
    )


def get_form_answers(
    session: Session,
    user: User,
    application_id: uuid.UUID,
) -> FormAnswersResponse | None:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")
    cache = get_app_autopilot(application).get("form_answers")
    if not isinstance(cache, dict):
        return None
    answers_raw = cache.get("answers") or []
    answers = [
        FormAnswerItem(
            id=str(a.get("id") or f"q{i}"),
            question=str(a.get("question") or ""),
            answer=str(a.get("answer") or ""),
            tips=str(a.get("tips") or "") or None,
        )
        for i, a in enumerate(answers_raw)
        if isinstance(a, dict) and str(a.get("question") or "").strip()
    ]
    if not answers:
        return None
    return FormAnswersResponse(
        application_id=str(application.id),
        company=job.company,
        title=job.title,
        answers=answers,
        generated_at=cache.get("generated_at"),
    )


def generate_and_store_form_answers(
    session: Session,
    user: User,
    application_id: uuid.UUID,
    payload: FormAnswersRequest,
) -> FormAnswersResponse:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")

    questions = [q.prompt.strip() for q in payload.questions if q.prompt.strip()]
    if not questions:
        raise APIError(422, "At least one question is required", "VALIDATION_ERROR")

    master: MasterResume | None = _optional_master(session, user)
    cv_excerpt = (master.raw_text or "")[:6000] if master else ""
    skills = list(user.parsed_skills or [])

    enforce_daily_generation_guard(session, user.id)
    try:
        raw = generate_form_answers(
            company=job.company,
            title=job.title,
            job_description=(job.description or "")[:5000],
            questions=questions,
            candidate_name=user.name,
            skills=skills,
            cv_excerpt=cv_excerpt,
            user_id=user.id,
            session=session,
        )
        answers_data = [a for a in (raw.get("answers") or []) if isinstance(a, dict)]
    except (LLMError, Exception):
        answers_data = []

    by_id = {str(a.get("id")): a for a in answers_data if a.get("id")}
    by_q = {str(a.get("question") or "").strip(): a for a in answers_data}

    answers: list[FormAnswerItem] = []
    for i, q in enumerate(questions):
        matched = by_id.get(f"q{i}") or by_q.get(q)
        if matched is None and i < len(answers_data):
            matched = answers_data[i]
        if matched is None:
            matched = {
                "answer": (
                    f"I am excited about the {job.title} role at {job.company}. "
                    f"My background includes {', '.join(skills[:5]) or 'relevant experience'} "
                    f"and I would welcome the chance to contribute."
                ),
                "tips": "Personalise with a concrete project metric before pasting.",
            }
        answers.append(
            FormAnswerItem(
                id=str(matched.get("id") or f"q{i}"),
                question=q,
                answer=str(matched.get("answer") or "").strip() or f"(Edit before submitting) {q}",
                tips=str(matched.get("tips") or "") or None,
            )
        )

    generated_at = datetime.now(timezone.utc).isoformat()
    patch_app_autopilot(
        application,
        form_answers={
            "answers": [a.model_dump() for a in answers],
            "generated_at": generated_at,
        },
    )
    session.flush()
    return FormAnswersResponse(
        application_id=str(application.id),
        company=job.company,
        title=job.title,
        answers=answers,
        generated_at=generated_at,
    )
