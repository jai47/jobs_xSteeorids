"""CRUD and draft generation for LinkedIn network contacts."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.network import LINKEDIN_NOTE_MAX, NetworkContactCreate, NetworkContactUpdate
from db.models import Application, Job, NetworkContact, User
from llm.linkedin_outreach import generate_linkedin_note
from services.llm_generation_guard import enforce_daily_generation_guard

VALID_ROLE_TAGS = frozenset({"recruiter", "hiring_manager", "employee", "agency", "other"})
VALID_STATUSES = frozenset({"drafted", "ready", "sent", "accepted", "replied", "closed"})
VALID_TEMPLATES = frozenset({"referral", "cold", "follow_up"})
FOLLOW_UP_DAYS = 7


def _parse_uuid(value: str | None, field: str) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise APIError(422, f"Invalid {field}", "VALIDATION_ERROR") from exc


def to_response_dict(contact: NetworkContact) -> dict:
    today = date.today()
    overdue = bool(
        contact.follow_up_due
        and contact.status == "sent"
        and contact.follow_up_due < today
    )
    return {
        "id": str(contact.id),
        "application_id": str(contact.application_id) if contact.application_id else None,
        "job_id": str(contact.job_id) if contact.job_id else None,
        "company": contact.company or "",
        "person_name": contact.person_name,
        "linkedin_url": contact.linkedin_url,
        "role_tag": contact.role_tag,
        "status": contact.status,
        "message_draft": contact.message_draft,
        "message_template": contact.message_template,
        "sent_at": contact.sent_at,
        "follow_up_due": contact.follow_up_due,
        "notes": contact.notes,
        "is_follow_up_overdue": overdue,
        "agent_enabled": bool(getattr(contact, "agent_enabled", False)),
        "agent_step": getattr(contact, "agent_step", None),
        "next_action_at": getattr(contact, "next_action_at", None),
        "nudge_count": int(getattr(contact, "nudge_count", 0) or 0),
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


def list_contacts(
    session: Session,
    user: User,
    *,
    status: str | None = None,
    company: str | None = None,
    application_id: uuid.UUID | None = None,
) -> list[NetworkContact]:
    query = session.query(NetworkContact).filter_by(user_id=user.id)
    if status:
        if status not in VALID_STATUSES:
            raise APIError(422, "Invalid status filter", "VALIDATION_ERROR")
        query = query.filter(NetworkContact.status == status)
    if company:
        query = query.filter(NetworkContact.company.ilike(f"%{company.strip()}%"))
    if application_id is not None:
        query = query.filter(NetworkContact.application_id == application_id)
    return query.order_by(NetworkContact.updated_at.desc()).all()


def get_contact(session: Session, user: User, contact_id: uuid.UUID) -> NetworkContact:
    contact = (
        session.query(NetworkContact)
        .filter_by(id=contact_id, user_id=user.id)
        .first()
    )
    if contact is None:
        raise APIError(404, "Network contact not found", "NOT_FOUND")
    return contact


def _resolve_application_context(
    session: Session,
    user: User,
    application_id: uuid.UUID | None,
    company_override: str | None,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str, Job | None]:
    if application_id is None:
        company = (company_override or "").strip() or "Unknown"
        return None, None, company, None

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
    company = (company_override or job.company or "").strip() or "Unknown"
    return application.id, job.id, company, job


def create_contact(
    session: Session,
    user: User,
    payload: NetworkContactCreate,
) -> NetworkContact:
    application_uuid = _parse_uuid(payload.application_id, "application_id")
    application_id, job_id, company, job = _resolve_application_context(
        session,
        user,
        application_uuid,
        payload.company,
    )

    contact = NetworkContact(
        id=uuid.uuid4(),
        user_id=user.id,
        application_id=application_id,
        job_id=job_id,
        company=company,
        person_name=payload.person_name.strip(),
        linkedin_url=payload.linkedin_url.strip(),
        role_tag=payload.role_tag,
        status="drafted",
        message_template=payload.message_template,
        notes=payload.notes,
    )
    session.add(contact)
    session.flush()

    if payload.generate_draft:
        draft_contact_message(session, user, contact, job=job)

    return contact


def update_contact(
    session: Session,
    user: User,
    contact_id: uuid.UUID,
    payload: NetworkContactUpdate,
) -> NetworkContact:
    contact = get_contact(session, user, contact_id)
    data = payload.model_dump(exclude_unset=True)

    if "status" in data and data["status"] not in VALID_STATUSES:
        raise APIError(422, "Invalid status", "VALIDATION_ERROR")
    if "role_tag" in data and data["role_tag"] not in VALID_ROLE_TAGS:
        raise APIError(422, "Invalid role_tag", "VALIDATION_ERROR")
    if "message_template" in data and data["message_template"] not in VALID_TEMPLATES:
        raise APIError(422, "Invalid message_template", "VALIDATION_ERROR")
    if "message_draft" in data and data["message_draft"] is not None:
        draft = data["message_draft"].strip()
        if len(draft) > LINKEDIN_NOTE_MAX:
            raise APIError(
                422,
                f"message_draft must be ≤ {LINKEDIN_NOTE_MAX} characters",
                "VALIDATION_ERROR",
            )
        data["message_draft"] = draft
        if draft and contact.status == "drafted":
            data.setdefault("status", "ready")

    for key, value in data.items():
        setattr(contact, key, value)

    contact.updated_at = datetime.now(timezone.utc)
    session.flush()
    return contact


def delete_contact(session: Session, user: User, contact_id: uuid.UUID) -> None:
    contact = get_contact(session, user, contact_id)
    session.delete(contact)
    session.flush()


def draft_contact_message(
    session: Session,
    user: User,
    contact: NetworkContact,
    *,
    job: Job | None = None,
) -> NetworkContact:
    enforce_daily_generation_guard(session, user.id)

    if job is None and contact.job_id is not None:
        job = session.get(Job, contact.job_id)

    skills = list(user.parsed_skills or [])
    try:
        note = generate_linkedin_note(
            person_name=contact.person_name,
            role_tag=contact.role_tag,
            template=contact.message_template or "referral",
            company=contact.company or (job.company if job else "the company"),
            job_title=job.title if job else None,
            job_description=job.description if job else None,
            candidate_name=user.name,
            skills=skills,
            user_id=user.id,
            session=session,
        )
    except LLMError as exc:
        raise APIError(502, str(exc), "LLM_ERROR") from exc

    contact.message_draft = note
    contact.status = "ready"
    contact.updated_at = datetime.now(timezone.utc)
    session.flush()
    return contact


def mark_contact_sent(session: Session, user: User, contact_id: uuid.UUID) -> NetworkContact:
    contact = get_contact(session, user, contact_id)
    now = datetime.now(timezone.utc)
    contact.status = "sent"
    contact.sent_at = now
    contact.follow_up_due = (now + timedelta(days=FOLLOW_UP_DAYS)).date()
    contact.updated_at = now
    session.flush()
    from services.networking_agent import on_contact_marked_sent

    on_contact_marked_sent(session, contact)
    return contact
