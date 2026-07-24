"""Networking Agent: sequenced connect → follow-up → nudge drafts until reply."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from db.models import Job, NetworkContact, User
from llm.linkedin_outreach import generate_linkedin_note
from services.llm_generation_guard import enforce_daily_generation_guard
from services.network_contacts import draft_contact_message, get_contact, to_response_dict
from services.notifications.producers import _enqueue

FOLLOW_UP_AFTER_DAYS = 7
NUDGE_AFTER_DAYS = 7
MAX_NUDGES = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _notify(session: Session, user_id: uuid.UUID, title: str, body: str, contact_id: uuid.UUID) -> None:
    _enqueue(
        session,
        user_id=user_id,
        type_="networking_agent",
        channel="in_app",
        payload={"title": title, "body": body, "contact_id": str(contact_id)},
        dedupe_key=f"networking_agent:{contact_id}:{_now().date().isoformat()}:{title[:40]}",
    )


def enroll_contact(
    session: Session,
    user: User,
    contact_id: uuid.UUID,
    *,
    generate_now: bool = True,
) -> NetworkContact:
    contact = get_contact(session, user, contact_id)
    contact.agent_enabled = True
    contact.agent_step = contact.agent_step or "connect"
    contact.next_action_at = _now()
    contact.nudge_count = contact.nudge_count or 0
    meta = dict(contact.agent_meta or {})
    meta["enrolled_at"] = _now().isoformat()
    contact.agent_meta = meta
    contact.updated_at = _now()

    if generate_now and not (contact.message_draft and contact.message_draft.strip()):
        job = session.get(Job, contact.job_id) if contact.job_id else None
        try:
            draft_contact_message(session, user, contact, job=job)
        except (LLMError, APIError):
            contact.message_draft = (
                f"Hi {contact.person_name.split()[0] if contact.person_name else ''} — "
                f"exploring opportunities at {contact.company}. Would welcome a brief chat."
            )[:300]
            contact.status = "ready"
        contact.agent_step = "connect"

    session.flush()
    _notify(
        session,
        user.id,
        f"Networking Agent: ready to connect with {contact.person_name}",
        "Open the extension or My Networks, copy the note, and send on LinkedIn. "
        "The agent will schedule follow-ups after you mark sent.",
        contact.id,
    )
    session.flush()
    return contact


def pause_contact(session: Session, user: User, contact_id: uuid.UUID) -> NetworkContact:
    contact = get_contact(session, user, contact_id)
    contact.agent_enabled = False
    contact.agent_step = "paused"
    contact.next_action_at = None
    contact.updated_at = _now()
    session.flush()
    return contact


def mark_agent_replied(session: Session, user: User, contact_id: uuid.UUID) -> NetworkContact:
    contact = get_contact(session, user, contact_id)
    contact.status = "replied"
    contact.agent_step = "replied"
    contact.agent_enabled = False
    contact.next_action_at = None
    contact.updated_at = _now()
    session.flush()
    return contact


def on_contact_marked_sent(session: Session, contact: NetworkContact) -> None:
    """Advance agent schedule after user marks a message as sent."""
    if not contact.agent_enabled:
        return
    step = contact.agent_step or "connect"
    if step == "connect":
        contact.agent_step = "awaiting_accept"
        contact.next_action_at = _now() + timedelta(days=FOLLOW_UP_AFTER_DAYS)
        contact.message_template = "follow_up"
    elif step in {"follow_up", "awaiting_accept"}:
        contact.agent_step = "nudge"
        contact.next_action_at = _now() + timedelta(days=NUDGE_AFTER_DAYS)
    elif step == "nudge":
        if (contact.nudge_count or 0) >= MAX_NUDGES:
            contact.agent_enabled = False
            contact.agent_step = "paused"
            contact.next_action_at = None
        else:
            contact.next_action_at = _now() + timedelta(days=NUDGE_AFTER_DAYS)
    contact.updated_at = _now()
    session.flush()


def _draft_step_message(
    session: Session,
    user: User,
    contact: NetworkContact,
    *,
    template: str,
) -> str:
    enforce_daily_generation_guard(session, user.id)
    job = session.get(Job, contact.job_id) if contact.job_id else None
    try:
        return generate_linkedin_note(
            person_name=contact.person_name,
            role_tag=contact.role_tag,
            template=template,
            company=contact.company or (job.company if job else "the company"),
            job_title=job.title if job else None,
            job_description=job.description if job else None,
            candidate_name=user.name,
            skills=list(user.parsed_skills or []),
            user_id=user.id,
            session=session,
        )
    except Exception:
        return (
            f"Hi {contact.person_name.split()[0] if contact.person_name else ''} — "
            f"just following up regarding {contact.company}. Happy to share more context anytime."
        )[:300]


def process_due_actions(session: Session, user: User) -> list[dict[str, Any]]:
    """Generate next drafts for due agent contacts. Does not send on LinkedIn."""
    now = _now()
    due = (
        session.query(NetworkContact)
        .filter(
            NetworkContact.user_id == user.id,
            NetworkContact.agent_enabled.is_(True),
            NetworkContact.next_action_at.isnot(None),
            NetworkContact.next_action_at <= now,
            NetworkContact.agent_step.notin_(["replied", "paused"]),
        )
        .order_by(NetworkContact.next_action_at.asc())
        .limit(20)
        .all()
    )
    actions: list[dict[str, Any]] = []
    for contact in due:
        step = contact.agent_step or "connect"
        if step == "connect":
            if not contact.message_draft:
                contact.message_draft = _draft_step_message(session, user, contact, template="cold")
            contact.status = "ready"
            contact.message_template = "cold"
            action_type = "send_connect"
            title = f"Agent: send connection to {contact.person_name}"
        elif step in {"awaiting_accept", "follow_up"}:
            contact.message_draft = _draft_step_message(session, user, contact, template="follow_up")
            contact.status = "ready"
            contact.message_template = "follow_up"
            contact.agent_step = "follow_up"
            action_type = "send_follow_up"
            title = f"Agent: follow up with {contact.person_name}"
        else:  # nudge
            contact.nudge_count = int(contact.nudge_count or 0) + 1
            contact.message_draft = _draft_step_message(session, user, contact, template="follow_up")
            contact.status = "ready"
            action_type = "send_nudge"
            title = f"Agent: nudge {contact.person_name} ({contact.nudge_count}/{MAX_NUDGES})"
            if contact.nudge_count >= MAX_NUDGES:
                # After drafting final nudge, pause once marked sent
                pass

        # Clear due until user marks sent (prevents re-draft spam)
        contact.next_action_at = None
        contact.updated_at = now
        _notify(session, user.id, title, contact.message_draft or "", contact.id)
        actions.append(
            {
                "contact": to_response_dict(contact),
                "action_type": action_type,
                "message": contact.message_draft,
                "linkedin_url": contact.linkedin_url,
            }
        )
    session.flush()
    return actions


def list_agent_queue(session: Session, user: User) -> dict[str, Any]:
    enrolled = (
        session.query(NetworkContact)
        .filter(NetworkContact.user_id == user.id, NetworkContact.agent_enabled.is_(True))
        .order_by(NetworkContact.updated_at.desc())
        .all()
    )
    ready = [c for c in enrolled if c.status == "ready" and c.message_draft]
    upcoming = [
        c
        for c in enrolled
        if c.next_action_at is not None and c.status != "ready"
    ]
    return {
        "enrolled": [to_response_dict(c) for c in enrolled],
        "ready_to_send": [
            {
                "contact": to_response_dict(c),
                "action_type": c.agent_step or "connect",
                "message": c.message_draft,
                "linkedin_url": c.linkedin_url,
            }
            for c in ready
        ],
        "upcoming": [
            {
                "contact_id": str(c.id),
                "person_name": c.person_name,
                "agent_step": c.agent_step,
                "next_action_at": c.next_action_at.isoformat() if c.next_action_at else None,
            }
            for c in upcoming
        ],
        "tip": (
            "The agent drafts and schedules. You (or the Chrome extension) send on LinkedIn, "
            "then mark sent so the next nudge is scheduled."
        ),
    }
