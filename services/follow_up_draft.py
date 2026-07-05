"""Template-first follow-up draft messages."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from api.deps import LLMError
from db.models import Application, Job, User
from services.llm_generation_guard import enforce_daily_generation_guard

FOLLOW_UP_TEMPLATE = """Subject: Following up on my application — {title}

Dear {company} Hiring Team,

I hope this message finds you well. I wanted to follow up on my application for the {title} position, which I submitted on {applied_date} ({days_since} days ago).

I remain very interested in the opportunity and believe my background would be a strong fit for your team. I would welcome any update on the status of my application or the chance to discuss how I can contribute.

Thank you for your time and consideration.

Best regards,
{name}"""


def days_since_applied(application: Application) -> int | None:
    if application.applied_at is None:
        return None
    applied = application.applied_at
    if applied.tzinfo is None:
        applied = applied.replace(tzinfo=timezone.utc)
    delta = date.today() - applied.date()
    return max(delta.days, 0)


def render_follow_up_draft(application: Application, job: Job, user: User) -> str:
    days = days_since_applied(application) or 0
    applied_date = "unknown date"
    if application.applied_at:
        applied_date = application.applied_at.date().isoformat()
    return FOLLOW_UP_TEMPLATE.format(
        title=job.title,
        company=job.company,
        applied_date=applied_date,
        days_since=days,
        name=user.name,
    )


def personalise_follow_up_draft(
    session: Session,
    user: User,
    application: Application,
    job: Job,
) -> str:
    """Optional LLM personalisation (one call, purpose follow_up_personalise)."""
    enforce_daily_generation_guard(session, user.id)
    base = render_follow_up_draft(application, job, user)
    from llm.client import call_llm

    prompt = (
        "Personalise this follow-up email template. Keep facts unchanged; do not invent "
        "experience or claims. Return plain text only.\n\n"
        f"JOB: {job.title} at {job.company}\n\n"
        f"TEMPLATE:\n{base}"
    )
    try:
        return call_llm(prompt, "follow_up_personalise", user.id, session, max_tokens=800).strip()
    except LLMError:
        raise
