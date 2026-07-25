"""Pydantic schemas for Job Search Autopilot."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TodayOpportunityItem(BaseModel):
    opportunity_id: str
    job_id: str
    company: str
    title: str
    overall_score: float | None = None
    url: str | None = None
    is_stale: bool = False
    reason: str = "high_score"


class TodayFollowUpItem(BaseModel):
    kind: Literal["application", "network"]
    id: str
    label: str
    company: str | None = None
    due: date | None = None
    overdue: bool = True
    detail: str | None = None


class TodayPacketGapItem(BaseModel):
    application_id: str
    company: str
    title: str
    missing: list[str]


class TodayInterviewNudge(BaseModel):
    application_id: str
    company: str
    title: str
    sub_status: str | None = None


class TodayQueueResponse(BaseModel):
    opportunities: list[TodayOpportunityItem]
    follow_ups: list[TodayFollowUpItem]
    packet_gaps: list[TodayPacketGapItem]
    interview_nudges: list[TodayInterviewNudge]
    tip: str = (
        "Work top to bottom: approve/prep packets, clear overdue follow-ups, then interview prep. "
        "You always send applications and LinkedIn messages yourself."
    )


class ChecklistItem(BaseModel):
    key: str
    label: str
    done: bool
    href: str | None = None


class ApplyPacketResponse(BaseModel):
    application_id: str
    company: str
    title: str
    job_url: str | None = None
    status: str
    resume_version_id: str | None = None
    ats_score_before: int | None = None
    ats_score_after: int | None = None
    cover_letter_status: str | None = None
    has_cover_letter_body: bool = False
    connect_note: str | None = None
    network_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    form_answers: list[dict[str, Any]] = Field(default_factory=list)
    checklist: list[ChecklistItem]
    ready: bool = False


class MessagePackItem(BaseModel):
    key: str
    label: str
    channel: Literal["linkedin", "email"]
    body: str
    day_offset: int = 0
    max_chars: int | None = None


class MessagePackResponse(BaseModel):
    application_id: str
    company: str
    title: str
    messages: list[MessagePackItem]
    generated_at: datetime | None = None


class MockQuestion(BaseModel):
    question: str
    tip: str | None = None
    related_theme: str | None = None


class InterviewPackResponse(BaseModel):
    application_id: str
    company: str
    title: str
    themes: list[str]
    stories: list[dict[str, Any]]
    uncovered_themes: list[str]
    mock_questions: list[MockQuestion]
    thank_you_note: str | None = None
    generated_at: datetime | None = None


class ReplyCoachRequest(BaseModel):
    message: str = Field(min_length=10, max_length=8000)
    application_id: str | None = None


class ReplyDraft(BaseModel):
    tone: str
    body: str


class ReplyCoachResponse(BaseModel):
    drafts: list[ReplyDraft]
    suggested_status: str | None = None
    next_steps: list[str] = Field(default_factory=list)


class OfferCompareRequest(BaseModel):
    application_ids: list[str] = Field(min_length=2, max_length=3)


class OfferCompareRow(BaseModel):
    application_id: str
    company: str
    title: str
    status: str
    salary_display: str | None = None
    remote_type: str | None = None
    country: str | None = None
    visa_mentioned: bool = False
    notes: str | None = None


class OfferCompareResponse(BaseModel):
    rows: list[OfferCompareRow]
    summary: str
    negotiation_bullets: list[str]


class ResumeSectionScore(BaseModel):
    section: str
    score: int
    feedback: str


class ResumeScoreResponse(BaseModel):
    overall_score: int
    summary: str
    sections: list[ResumeSectionScore]
    quick_wins: list[str]
    analyzed_at: datetime | None = None
    master_resume_id: str | None = None
    persona_label: str | None = None


class WeeklyPlanAction(BaseModel):
    action: str
    why: str
    effort: Literal["low", "medium", "high"] = "medium"


class WeeklyPlanResponse(BaseModel):
    period_label: str | None = None
    actions: list[WeeklyPlanAction]
    focus_skills: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class SuggestedAction(BaseModel):
    action: str
    label: str
    application_id: str | None = None
    path: str | None = None


class ChatVisualStat(BaseModel):
    label: str
    value: str
    tone: Literal["neutral", "accent", "warn", "ok"] = "neutral"


class ChatVisualJob(BaseModel):
    title: str
    company: str
    score: float | None = None
    opportunity_id: str | None = None
    url: str | None = None


class ChatVisualProgress(BaseModel):
    label: str
    value: int
    max: int = 100


class ChatVisualChecklistItem(BaseModel):
    label: str
    done: bool = False
    path: str | None = None


class ChatVisual(BaseModel):
    """Rich visual card embedded in a chat reply."""

    type: Literal[
        "stat_row",
        "job_list",
        "progress",
        "checklist",
        "quick_replies",
        "route_cta",
        "tip",
    ]
    title: str | None = None
    stats: list[ChatVisualStat] = Field(default_factory=list)
    jobs: list[ChatVisualJob] = Field(default_factory=list)
    progress: ChatVisualProgress | None = None
    checklist: list[ChatVisualChecklistItem] = Field(default_factory=list)
    quick_replies: list[str] = Field(default_factory=list)
    path: str | None = None
    label: str | None = None
    body: str | None = None


class ChatResponse(BaseModel):
    reply: str
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    visuals: list[ChatVisual] = Field(default_factory=list)
    mood: Literal["neutral", "encouraging", "urgent", "celebratory"] = "neutral"


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    visuals: list[ChatVisual] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    messages: list[ChatHistoryMessage]


class MasterResumeItem(BaseModel):
    id: str
    filename: str | None = None
    label: str | None = None
    is_active: bool
    uploaded_at: datetime | None = None


class MasterResumeListResponse(BaseModel):
    resumes: list[MasterResumeItem]


class MasterResumeUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


# --- Career-ops style extensions ---


class AutoPipelineRequest(BaseModel):
    description: str = Field(min_length=40, max_length=50000)
    url: str | None = Field(default=None, max_length=2000)
    company: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=300)
    country: str | None = Field(default=None, max_length=8)
    remote_type: str | None = Field(default=None, max_length=32)
    approve: bool = False
    track: bool = False


class AutoPipelineScores(BaseModel):
    skill_match: float
    role_match: float
    experience: float
    country_pref: float
    remote_pref: float
    fit: float
    visa: float


class AutoPipelineResponse(BaseModel):
    opportunity_id: str
    job_id: str
    application_id: str | None = None
    resume_version_id: str | None = None
    company: str
    title: str
    url: str | None = None
    overall_score: float
    classification: str
    scores: AutoPipelineScores
    fit_reasoning: str | None = None
    visa_status: str | None = None
    visa_reasoning: str | None = None
    tailored: bool = False
    created_at: datetime | None = None


class CompanyResearchRequest(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    job_title: str | None = Field(default=None, max_length=300)
    application_id: str | None = None
    force: bool = False


class CompanyResearchResponse(BaseModel):
    company: str
    job_title: str | None = None
    application_id: str | None = None
    cached: bool = False
    summary: str
    funding_or_stage: str | None = None
    leadership_notes: str | None = None
    press_signals: list[str] = Field(default_factory=list)
    comp_signals: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    green_flags: list[str] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)
    generated_at: str | None = None


class FormAnswerQuestion(BaseModel):
    id: str | None = None
    prompt: str = Field(min_length=3, max_length=2000)


class FormAnswersRequest(BaseModel):
    questions: list[FormAnswerQuestion] = Field(min_length=1, max_length=12)


class FormAnswerItem(BaseModel):
    id: str
    question: str
    answer: str
    tips: str | None = None


class FormAnswersResponse(BaseModel):
    application_id: str
    company: str
    title: str
    answers: list[FormAnswerItem]
    generated_at: str | None = None


class PatternStat(BaseModel):
    key: str
    count: int
    label: str


class PatternInsight(BaseModel):
    kind: str
    title: str
    detail: str
    severity: Literal["info", "warn"] = "info"


class PatternsResponse(BaseModel):
    total_opportunities: int
    total_applications: int
    reject_reasons: list[PatternStat]
    rejected_companies: list[PatternStat]
    rejected_archetypes: list[PatternStat]
    skipped_companies: list[PatternStat]
    insights: list[PatternInsight]
    summary: str | None = None
    generated_at: datetime | None = None


class TrainingScoreRequest(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str | None = Field(default=None, max_length=8000)
    cost_hours: float | None = Field(default=None, ge=0, le=2000)
    cost_money: float | None = Field(default=None, ge=0, le=100000)
    url: str | None = Field(default=None, max_length=2000)


class TrainingScoreResponse(BaseModel):
    title: str
    score: int
    verdict: Literal["worth_it", "maybe", "skip"]
    summary: str
    why: list[str] = Field(default_factory=list)
    opportunity_cost: list[str] = Field(default_factory=list)
    better_alternatives: list[str] = Field(default_factory=list)
    scored_at: datetime | None = None


class ProjectScoreRequest(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str | None = Field(default=None, max_length=8000)
    estimated_hours: float | None = Field(default=None, ge=0, le=2000)


class ProjectScoreResponse(BaseModel):
    title: str
    score: int
    verdict: Literal["build", "maybe", "skip"]
    summary: str
    why: list[str] = Field(default_factory=list)
    scope_tips: list[str] = Field(default_factory=list)
    resume_bullets: list[str] = Field(default_factory=list)
    scored_at: datetime | None = None
