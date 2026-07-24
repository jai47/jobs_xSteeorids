"""Reply coach: draft responses to recruiter messages."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.autopilot import ReplyCoachRequest, ReplyCoachResponse, ReplyDraft
from db.models import Application, Job, User
from llm.reply_coach import generate_reply_drafts
from services.llm_generation_guard import enforce_daily_generation_guard


def run_reply_coach(
    session: Session,
    user: User,
    payload: ReplyCoachRequest,
) -> ReplyCoachResponse:
    enforce_daily_generation_guard(session, user.id)
    job_title = None
    company = None
    if payload.application_id:
        try:
            app_id = uuid.UUID(str(payload.application_id))
        except ValueError as exc:
            raise APIError(422, "Invalid application_id", "VALIDATION_ERROR") from exc
        application = session.get(Application, app_id)
        if application is None or application.user_id != user.id:
            raise APIError(404, "Application not found", "NOT_FOUND")
        job = session.get(Job, application.job_id)
        if job:
            job_title = job.title
            company = job.company

    try:
        raw = generate_reply_drafts(
            message=payload.message,
            candidate_name=user.name,
            company=company,
            job_title=job_title,
            user_id=user.id,
            session=session,
        )
        drafts = [
            ReplyDraft(tone=str(d.get("tone") or "professional"), body=str(d.get("body") or "").strip())
            for d in (raw.get("drafts") or [])
            if isinstance(d, dict) and d.get("body")
        ]
        if not drafts:
            raise ValueError("no drafts")
        return ReplyCoachResponse(
            drafts=drafts[:3],
            suggested_status=raw.get("suggested_status"),
            next_steps=[str(s) for s in (raw.get("next_steps") or []) if str(s).strip()][:5],
        )
    except (LLMError, Exception):
        return ReplyCoachResponse(
            drafts=[
                ReplyDraft(
                    tone="professional",
                    body=(
                        f"Hi,\n\nThanks for your message — happy to continue the conversation. "
                        f"Please let me know the best next step.\n\nBest,\n{user.name}"
                    ),
                ),
                ReplyDraft(
                    tone="concise",
                    body=f"Thanks for reaching out. I'm available this week for a quick call.\n\n{user.name}",
                ),
            ],
            suggested_status="interviewing",
            next_steps=["Update tracker status", "Prepare interview pack"],
        )
