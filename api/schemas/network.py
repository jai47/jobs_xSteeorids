"""Pydantic schemas for LinkedIn network outreach contacts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

RoleTag = Literal["recruiter", "hiring_manager", "employee", "agency", "other"]
ContactStatus = Literal["drafted", "ready", "sent", "accepted", "replied", "closed"]
MessageTemplate = Literal["referral", "cold", "follow_up"]

LINKEDIN_NOTE_MAX = 300


class NetworkContactCreate(BaseModel):
    person_name: str = Field(min_length=1, max_length=200)
    linkedin_url: str = Field(min_length=8, max_length=500)
    role_tag: RoleTag = "recruiter"
    message_template: MessageTemplate = "referral"
    application_id: str | None = None
    company: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    generate_draft: bool = False

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin_url(cls, value: str) -> str:
        cleaned = value.strip()
        lowered = cleaned.lower()
        if "linkedin.com/" not in lowered:
            raise ValueError("linkedin_url must be a LinkedIn profile URL")
        if not lowered.startswith("http://") and not lowered.startswith("https://"):
            cleaned = "https://" + cleaned
        return cleaned


class NetworkContactUpdate(BaseModel):
    person_name: str | None = Field(default=None, min_length=1, max_length=200)
    linkedin_url: str | None = Field(default=None, min_length=8, max_length=500)
    role_tag: RoleTag | None = None
    status: ContactStatus | None = None
    message_draft: str | None = Field(default=None, max_length=LINKEDIN_NOTE_MAX)
    message_template: MessageTemplate | None = None
    notes: str | None = None
    follow_up_due: date | None = None
    company: str | None = Field(default=None, max_length=200)

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return NetworkContactCreate.validate_linkedin_url(value)


class NetworkContactResponse(BaseModel):
    id: str
    application_id: str | None = None
    job_id: str | None = None
    company: str
    person_name: str
    linkedin_url: str
    role_tag: str
    status: str
    message_draft: str | None = None
    message_template: str
    sent_at: datetime | None = None
    follow_up_due: date | None = None
    notes: str | None = None
    is_follow_up_overdue: bool = False
    agent_enabled: bool = False
    agent_step: str | None = None
    next_action_at: datetime | None = None
    nudge_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NetworkContactListResponse(BaseModel):
    contacts: list[NetworkContactResponse]


class NetworkingAgentQueueResponse(BaseModel):
    enrolled: list[NetworkContactResponse]
    ready_to_send: list[dict]
    upcoming: list[dict]
    tip: str


class ConversationAssistantRequest(BaseModel):
    thread_text: str = Field(min_length=10, max_length=12000)
    application_id: str | None = None
    contact_id: str | None = None
    voice_notes: str | None = Field(default=None, max_length=2000)


class ConversationDraft(BaseModel):
    tone: str
    body: str


class ConversationAssistantResponse(BaseModel):
    drafts: list[ConversationDraft]
    intent: str | None = None
    suggested_next_status: str | None = None


class JobImportRequest(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    company: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=8, max_length=1000)
    description: str | None = Field(default=None, max_length=50000)
    location: str | None = Field(default=None, max_length=200)
    source: str = Field(default="extension_import", max_length=80)


class JobImportResponse(BaseModel):
    job_id: str
    opportunity_id: str
    company: str
    title: str
    url: str
    overall_score: float | None = None
    message: str = "Job imported into your opportunities."


class HealthSummaryResponse(BaseModel):
    applications_total: int
    by_status: dict[str, int]
    network_contacts: int
    agent_enrolled: int
    agent_ready: int
    resume_versions: int
    has_active_resume: bool
    analytics_unlocked: bool
    qualifying_applications: int
    tip: str
