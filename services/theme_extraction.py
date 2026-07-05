"""Application theme persistence and extraction."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from api.deps import LLMError
from db.models import Application, ApplicationTheme, Job, User
from llm.star_themes import extract_themes_from_job

log = logging.getLogger(__name__)


def get_or_create_theme_row(session: Session, application_id: uuid.UUID) -> ApplicationTheme:
    row = session.query(ApplicationTheme).filter_by(application_id=application_id).first()
    if row is None:
        row = ApplicationTheme(application_id=application_id, status="pending", themes=[])
        session.add(row)
        session.flush()
    return row


def extract_themes_for_application(
    session: Session,
    user: User,
    application: Application,
    job: Job,
) -> ApplicationTheme:
    row = get_or_create_theme_row(session, application.id)
    row.status = "pending"
    session.flush()
    try:
        themes = extract_themes_from_job(
            job_title=job.title,
            company=job.company,
            job_description=job.description or "",
            user_id=user.id,
            session=session,
        )
        row.themes = themes[:3]
        row.status = "ready"
    except LLMError as exc:
        row.status = "failed"
        log.warning("Theme extraction failed for application %s: %s", application.id, exc)
    except Exception as exc:
        row.status = "failed"
        log.exception("Theme extraction error: %s", exc)
    session.flush()
    return row


def get_themes_for_application(session: Session, application_id: uuid.UUID) -> ApplicationTheme | None:
    return session.query(ApplicationTheme).filter_by(application_id=application_id).first()
