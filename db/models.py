"""
All models for the AI Career Copilot.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    dashboard_password = Column(String, nullable=False)
    nationality = Column(String)
    preferred_countries = Column(ARRAY(String), default=[])
    preferred_roles = Column(ARRAY(String), default=[])
    prefers_remote = Column(Boolean, default=False)
    salary_range_min = Column(Integer, nullable=True)
    salary_range_max = Column(Integer, nullable=True)
    salary_currency = Column(String(3), default="USD")
    years_experience = Column(Integer)
    parsed_skills = Column(ARRAY(String), default=[])
    blacklisted_companies = Column(ARRAY(String), default=[])
    blacklisted_roles = Column(ARRAY(String), default=[])
    blacklisted_locations = Column(ARRAY(String), default=[])
    score_warning_threshold = Column(Integer, default=40, nullable=False)
    cover_letter_angles = Column(JSONB, default=lambda: dict())
    notify_digest_email = Column(Boolean, default=True, nullable=False)
    notify_followup_email = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Company(Base):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False)
    country = Column(String)
    careers_url = Column(String)
    ats_type = Column(String)
    ai_job_count = Column(Integer, default=0)
    last_seen = Column(Date)
    visa_score_avg = Column(Float)
    is_visa_friendly = Column(Boolean)
    first_seen = Column(Date)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    url = Column(String, unique=True, nullable=False)
    company = Column(String, nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"))
    title = Column(String, nullable=False)
    country = Column(String)
    city = Column(String)
    remote_type = Column(String)
    salary_display = Column(String)
    visa_mentioned = Column(Boolean, default=False)
    visa_keywords = Column(ARRAY(String), default=[])
    skills_required = Column(ARRAY(String), default=[])
    experience_min = Column(Integer)
    description = Column(Text)
    posted_at = Column(Date)
    is_active = Column(Boolean, default=True)
    is_stale = Column(Boolean, default=False)
    last_verified = Column(Date)
    archetype = Column(String, nullable=True)
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    salary_currency = Column(String(3), nullable=True)
    salary_period = Column(String, nullable=True)
    salary_usd_min = Column(Integer, nullable=True)
    salary_usd_max = Column(Integer, nullable=True)
    salary_currency_assumed = Column(Boolean, default=False)
    legitimacy_flags = Column(JSONB, default=list)
    dedup_fingerprint = Column(String(64), nullable=True, index=True)
    description_hash = Column(String(32), nullable=True)
    repost_of_job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_source_external_id"),
    )


class ScoredOpportunity(Base):
    __tablename__ = "scored_opportunities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    score_skill_match = Column(Float)
    score_role_match = Column(Float)
    score_experience = Column(Float)
    score_country_pref = Column(Float)
    score_remote_pref = Column(Float)
    score_fit = Column(Float)
    score_visa = Column(Integer)
    visa_status = Column(String)
    visa_reasoning = Column(Text)
    overall_score = Column(Float)
    classification = Column(String)
    fit_reasoning = Column(Text)
    user_feedback = Column(String)
    reject_reason = Column(String)
    digest_date = Column(Date)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("job_id", "user_id", "digest_date", name="uq_job_user_date"),
    )


class MasterResume(Base):
    __tablename__ = "master_resumes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    filename = Column(String)
    raw_text = Column(Text)
    parsed_json = Column(JSON)
    is_active = Column(Boolean, default=True)
    uploaded_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    master_resume_id = Column(UUID(as_uuid=True), ForeignKey("master_resumes.id"))
    ats_score_before = Column(Integer)
    ats_score_after = Column(Integer)
    keywords_added = Column(ARRAY(String))
    skill_gaps = Column(ARRAY(String))
    tailored_markdown = Column(Text)
    latex_source = Column(Text)
    pdf_path = Column(String)
    json_resume = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    resume_version_id = Column(UUID(as_uuid=True), ForeignKey("resume_versions.id"))
    status = Column(String)
    applied_at = Column(DateTime(timezone=True))
    follow_up_due = Column(Date)
    followed_up_at = Column(DateTime(timezone=True))
    second_follow_up_due = Column(Date)
    notes = Column(Text)
    sub_status = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class CoverLetter(Base):
    __tablename__ = "cover_letters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False, default="pending")
    body = Column(Text)
    generation_count = Column(Integer, default=0)
    last_error = Column(Text)
    angles_snapshot = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_date = Column(Date, unique=True)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    status = Column(String)
    jobs_discovered = Column(Integer, default=0)
    jobs_after_dedup = Column(Integer, default=0)
    jobs_scored = Column(Integer, default=0)
    top_opportunities = Column(Integer, default=0)
    error_stage = Column(String)
    error_message = Column(Text)
    current_stage = Column(String)
    progress_log = Column(JSON, default=list)


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    provider = Column(String)
    model = Column(String)
    call_purpose = Column(String)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class SkillGapReport(Base):
    __tablename__ = "skill_gap_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    period_type = Column(String)
    period_start = Column(Date)
    period_end = Column(Date)
    top_missing_skills = Column(JSON)
    total_jobs_analysed = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class DailyDigest(Base):
    __tablename__ = "daily_digests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    digest_date = Column(Date, nullable=False)
    content_text = Column(Text, nullable=False)
    metrics_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "digest_date", name="uq_user_digest_date"),
    )


class FxRate(Base):
    __tablename__ = "fx_rates"

    currency = Column(String(3), primary_key=True)
    rate_to_usd = Column(Float, nullable=False)
    as_of = Column(Date, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, nullable=False)
    channel = Column(String, nullable=False)
    payload_json = Column(JSONB, nullable=False)
    dedupe_key = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False, default="pending")
    attempts = Column(Integer, default=0, nullable=False)
    scheduled_for = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class StarStory(Base):
    __tablename__ = "star_stories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="draft")
    title = Column(String, nullable=False)
    tags = Column(ARRAY(String), default=list)
    situation = Column(Text)
    task = Column(Text)
    action = Column(Text)
    result = Column(Text)
    reflection = Column(Text)
    source_job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    ai_drafted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class ApplicationTheme(Base):
    __tablename__ = "application_themes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    themes = Column(ARRAY(String), default=list)
    status = Column(String, nullable=False, default="pending")


class ApplicationStageEvent(Base):
    __tablename__ = "application_stage_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=True)
    from_sub = Column(String, nullable=True)
    to_sub = Column(String, nullable=True)
    occurred_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)