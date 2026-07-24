"""Compact job-health summary for extension + Today."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.schemas.network import HealthSummaryResponse
from db.models import Application, NetworkContact, ResumeVersion, User
from services.application_analytics import UNLOCK_THRESHOLD
from services.onboarding import user_has_active_resume


def build_health_summary(session: Session, user: User) -> HealthSummaryResponse:
    apps = session.query(Application).filter_by(user_id=user.id).all()
    by_status: dict[str, int] = {}
    for app in apps:
        key = app.status or "unknown"
        by_status[key] = by_status.get(key, 0) + 1

    qualifying = sum(
        1
        for a in apps
        if a.status in {"applied", "interviewing", "offer", "accepted", "rejected"}
    )
    network_count = (
        session.query(func.count(NetworkContact.id)).filter_by(user_id=user.id).scalar() or 0
    )
    agent_enrolled = (
        session.query(func.count(NetworkContact.id))
        .filter_by(user_id=user.id, agent_enabled=True)
        .scalar()
        or 0
    )
    agent_ready = (
        session.query(func.count(NetworkContact.id))
        .filter(
            NetworkContact.user_id == user.id,
            NetworkContact.agent_enabled.is_(True),
            NetworkContact.status == "ready",
        )
        .scalar()
        or 0
    )
    resume_versions = (
        session.query(func.count(ResumeVersion.id)).filter_by(user_id=user.id).scalar() or 0
    )

    return HealthSummaryResponse(
        applications_total=len(apps),
        by_status=by_status,
        network_contacts=int(network_count),
        agent_enrolled=int(agent_enrolled),
        agent_ready=int(agent_ready),
        resume_versions=int(resume_versions),
        has_active_resume=user_has_active_resume(session, user.id),
        analytics_unlocked=qualifying >= UNLOCK_THRESHOLD,
        qualifying_applications=qualifying,
        tip=(
            "360° view: resumes → applications → interviews → offers. "
            "Clear agent-ready sends and packet gaps on Today first."
        ),
    )
