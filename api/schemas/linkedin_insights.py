"""Pydantic schemas for LinkedIn profile coach + find-network suggestions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.schemas.network import NetworkContactResponse, RoleTag

ProfileSource = Literal["pasted_profile", "extension"]


class LinkedInProfileAnalyzeRequest(BaseModel):
    """Profile text from paste or Chrome extension. Server never logs into LinkedIn."""

    profile_text: str = Field(min_length=80, max_length=50000)
    target_roles: list[str] | None = None
    source: ProfileSource = "pasted_profile"


class ProfileSectionScore(BaseModel):
    section: str
    score: int = Field(ge=0, le=100)
    status: str  # strong | improve | missing
    feedback: str
    suggested_rewrite: str | None = None


class LinkedInProfileAnalysisResponse(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    summary: str
    sections: list[ProfileSectionScore]
    quick_wins: list[str] = Field(default_factory=list)
    headline_suggestion: str | None = None
    about_suggestion: str | None = None
    analyzed_at: datetime | None = None
    source: str = "pasted_profile"


class FindNetworkRequest(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    application_id: str | None = None
    job_description: str | None = Field(default=None, max_length=8000)


class NetworkSearchSuggestion(BaseModel):
    role_tag: str
    title_query: str
    why: str
    linkedin_search_url: str
    priority: int = Field(ge=1, le=5)


class FindNetworkResponse(BaseModel):
    company: str
    job_title: str | None = None
    strategy_summary: str
    suggestions: list[NetworkSearchSuggestion]
    tip: str = (
        "Open each LinkedIn search while logged into your account, pick real people, "
        "then import via the Chrome extension or add them in My Networks."
    )


class ImportContactItem(BaseModel):
    person_name: str = Field(min_length=1, max_length=200)
    linkedin_url: str = Field(min_length=8, max_length=500)
    role_tag: RoleTag | None = None
    headline: str | None = Field(default=None, max_length=500)
    company: str | None = Field(default=None, max_length=200)

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


class ImportContactsRequest(BaseModel):
    """Bulk import from Chrome extension (people search / company people page)."""

    contacts: list[ImportContactItem] = Field(min_length=1, max_length=50)
    application_id: str | None = None
    company: str | None = Field(default=None, max_length=200)
    generate_drafts: bool = False
    source: Literal["extension", "manual"] = "extension"


class ImportContactsResponse(BaseModel):
    created: list[NetworkContactResponse]
    skipped: int = 0
    skipped_urls: list[str] = Field(default_factory=list)
