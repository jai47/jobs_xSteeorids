"""Post-approve background enrichment (cover letter + theme extraction)."""

from __future__ import annotations

import logging
import uuid

from db.engine import SessionLocal
from db.models import Application, Job, User
from services.cover_letters import generate_cover_letter
from services.theme_extraction import extract_themes_for_application

log = logging.getLogger(__name__)


def run_cover_letter_enrichment(application_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Background task: generate cover letter after approve (fail-soft)."""
    session = SessionLocal()
    try:
        application = session.get(Application, application_id)
        user = session.get(User, user_id)
        if application is None or user is None:
            return
        job = session.get(Job, application.job_id)
        if job is None:
            return
        generate_cover_letter(session, user, application, job, check_limits=False, allow_generating_state=True)
        session.commit()
    except Exception:
        log.exception("Cover letter enrichment failed for application %s", application_id)
        session.rollback()
    finally:
        session.close()

    # After cover letter, seed Apply Packet bits (message pack + network suggestions).
    try:
        from services.autopilot.apply_packet import ensure_apply_packet_bits

        ensure_apply_packet_bits(application_id, user_id)
    except Exception:
        log.exception("Apply packet enrichment failed for application %s", application_id)


def run_theme_extraction(application_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Background task: extract interview themes after approve (fail-soft)."""
    session = SessionLocal()
    try:
        application = session.get(Application, application_id)
        user = session.get(User, user_id)
        if application is None or user is None:
            return
        job = session.get(Job, application.job_id)
        if job is None:
            return
        extract_themes_for_application(session, user, application, job)
        session.commit()
    except Exception:
        log.exception("Theme extraction failed for application %s", application_id)
        session.rollback()
    finally:
        session.close()
