"""LinkedIn conversation assistant (voice-matched replies)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.network import (
    ConversationAssistantRequest,
    ConversationAssistantResponse,
    ConversationDraft,
)
from db.models import Application, Job, NetworkContact, User
from llm.conversation_assistant import generate_conversation_replies
from services.autopilot.state import get_user_autopilot, patch_user_autopilot
from services.llm_generation_guard import enforce_daily_generation_guard


def run_conversation_assistant(
    session: Session,
    user: User,
    payload: ConversationAssistantRequest,
) -> ConversationAssistantResponse:
    enforce_daily_generation_guard(session, user.id)
    company = None
    job_title = None

    if payload.contact_id:
        try:
            cid = uuid.UUID(str(payload.contact_id))
        except ValueError as exc:
            raise APIError(422, "Invalid contact_id", "VALIDATION_ERROR") from exc
        contact = session.get(NetworkContact, cid)
        if contact is None or contact.user_id != user.id:
            raise APIError(404, "Contact not found", "NOT_FOUND")
        company = contact.company
        if contact.job_id:
            job = session.get(Job, contact.job_id)
            if job:
                job_title = job.title
                company = company or job.company

    if payload.application_id:
        try:
            aid = uuid.UUID(str(payload.application_id))
        except ValueError as exc:
            raise APIError(422, "Invalid application_id", "VALIDATION_ERROR") from exc
        application = session.get(Application, aid)
        if application is None or application.user_id != user.id:
            raise APIError(404, "Application not found", "NOT_FOUND")
        job = session.get(Job, application.job_id)
        if job:
            company = company or job.company
            job_title = job_title or job.title

    voice = payload.voice_notes
    if not voice:
        stored = get_user_autopilot(user).get("conversation_voice")
        if isinstance(stored, str):
            voice = stored

    try:
        raw = generate_conversation_replies(
            thread_text=payload.thread_text,
            candidate_name=user.name,
            voice_notes=voice,
            company=company,
            job_title=job_title,
            user_id=user.id,
            session=session,
        )
        drafts = [
            ConversationDraft(
                tone=str(d.get("tone") or "warm"),
                body=str(d.get("body") or "").strip(),
            )
            for d in (raw.get("drafts") or [])
            if isinstance(d, dict) and d.get("body")
        ]
        if not drafts:
            raise ValueError("no drafts")
        if payload.voice_notes:
            patch_user_autopilot(user, conversation_voice=payload.voice_notes.strip()[:1500])
            session.flush()
        return ConversationAssistantResponse(
            drafts=drafts[:3],
            intent=raw.get("intent"),
            suggested_next_status=raw.get("suggested_next_status"),
        )
    except (LLMError, Exception):
        return ConversationAssistantResponse(
            drafts=[
                ConversationDraft(
                    tone="warm",
                    body=(
                        f"Thanks for the note — happy to continue the conversation. "
                        f"What would be the best next step on your side?\n\n{user.name}"
                    ),
                ),
                ConversationDraft(
                    tone="concise",
                    body=f"Appreciate you reaching out. I'm available this week if helpful.\n\n{user.name}",
                ),
            ],
            intent="follow_up",
            suggested_next_status="replied",
        )
