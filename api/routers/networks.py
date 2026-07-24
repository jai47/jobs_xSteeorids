"""LinkedIn network outreach routes (draft + track; user sends on LinkedIn)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.network import (
    ConversationAssistantRequest,
    ConversationAssistantResponse,
    JobImportRequest,
    JobImportResponse,
    NetworkContactCreate,
    NetworkContactListResponse,
    NetworkContactResponse,
    NetworkContactUpdate,
    NetworkingAgentQueueResponse,
)
from db.models import User
from services.conversation_assistant import run_conversation_assistant
from services.job_import import import_job_from_extension
from services.network_contacts import (
    create_contact,
    delete_contact,
    draft_contact_message,
    get_contact,
    list_contacts,
    mark_contact_sent,
    to_response_dict,
    update_contact,
)
from services.networking_agent import (
    enroll_contact,
    list_agent_queue,
    mark_agent_replied,
    pause_contact,
    process_due_actions,
)

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get("/agent/queue", response_model=NetworkingAgentQueueResponse)
def get_agent_queue(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkingAgentQueueResponse:
    data = list_agent_queue(db, user)
    return NetworkingAgentQueueResponse(
        enrolled=[NetworkContactResponse(**c) for c in data["enrolled"]],
        ready_to_send=data["ready_to_send"],
        upcoming=data["upcoming"],
        tip=data["tip"],
    )


@router.post("/agent/process", response_model=NetworkingAgentQueueResponse)
def post_agent_process(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkingAgentQueueResponse:
    """Advance due agent actions (draft next messages + notify). Does not send on LinkedIn."""
    process_due_actions(db, user)
    data = list_agent_queue(db, user)
    return NetworkingAgentQueueResponse(
        enrolled=[NetworkContactResponse(**c) for c in data["enrolled"]],
        ready_to_send=data["ready_to_send"],
        upcoming=data["upcoming"],
        tip=data["tip"],
    )


@router.post("/conversation", response_model=ConversationAssistantResponse)
def post_conversation(
    payload: ConversationAssistantRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConversationAssistantResponse:
    """AI LinkedIn Conversation Assistant — drafts replies in your voice (you send)."""
    return run_conversation_assistant(db, user, payload)


@router.post("/jobs/import", response_model=JobImportResponse)
def post_job_import(
    payload: JobImportRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> JobImportResponse:
    """Import a job posting captured by the Chrome extension."""
    return import_job_from_extension(db, user, payload)


@router.get("", response_model=NetworkContactListResponse)
def get_networks(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    status: str | None = Query(default=None),
    company: str | None = Query(default=None),
    application_id: uuid.UUID | None = Query(default=None),
) -> NetworkContactListResponse:
    contacts = list_contacts(
        db,
        user,
        status=status,
        company=company,
        application_id=application_id,
    )
    return NetworkContactListResponse(
        contacts=[NetworkContactResponse(**to_response_dict(c)) for c in contacts]
    )


@router.post("", response_model=NetworkContactResponse, status_code=201)
def post_network(
    payload: NetworkContactCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkContactResponse:
    contact = create_contact(db, user, payload)
    return NetworkContactResponse(**to_response_dict(contact))


@router.get("/{contact_id}", response_model=NetworkContactResponse)
def get_network(
    contact_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkContactResponse:
    contact = get_contact(db, user, contact_id)
    return NetworkContactResponse(**to_response_dict(contact))


@router.patch("/{contact_id}", response_model=NetworkContactResponse)
def patch_network(
    contact_id: uuid.UUID,
    payload: NetworkContactUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkContactResponse:
    contact = update_contact(db, user, contact_id, payload)
    return NetworkContactResponse(**to_response_dict(contact))


@router.delete("/{contact_id}", status_code=204)
def delete_network(
    contact_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    delete_contact(db, user, contact_id)
    return Response(status_code=204)


@router.post("/{contact_id}/draft", response_model=NetworkContactResponse)
def post_network_draft(
    contact_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkContactResponse:
    contact = get_contact(db, user, contact_id)
    contact = draft_contact_message(db, user, contact)
    return NetworkContactResponse(**to_response_dict(contact))


@router.post("/{contact_id}/mark-sent", response_model=NetworkContactResponse)
def post_network_mark_sent(
    contact_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkContactResponse:
    contact = mark_contact_sent(db, user, contact_id)
    return NetworkContactResponse(**to_response_dict(contact))


@router.post("/{contact_id}/agent/enroll", response_model=NetworkContactResponse)
def post_agent_enroll(
    contact_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkContactResponse:
    contact = enroll_contact(db, user, contact_id)
    return NetworkContactResponse(**to_response_dict(contact))


@router.post("/{contact_id}/agent/pause", response_model=NetworkContactResponse)
def post_agent_pause(
    contact_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkContactResponse:
    contact = pause_contact(db, user, contact_id)
    return NetworkContactResponse(**to_response_dict(contact))


@router.post("/{contact_id}/agent/replied", response_model=NetworkContactResponse)
def post_agent_replied(
    contact_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkContactResponse:
    contact = mark_agent_replied(db, user, contact_id)
    return NetworkContactResponse(**to_response_dict(contact))
