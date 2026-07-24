"""List / activate / label master resumes (persona support)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError
from api.schemas.autopilot import MasterResumeItem, MasterResumeListResponse, MasterResumeUpdate
from db.models import MasterResume, User


def list_master_resumes(session: Session, user: User) -> MasterResumeListResponse:
    rows = (
        session.query(MasterResume)
        .filter_by(user_id=user.id)
        .order_by(MasterResume.uploaded_at.desc())
        .all()
    )
    return MasterResumeListResponse(
        resumes=[
            MasterResumeItem(
                id=str(r.id),
                filename=r.filename,
                label=r.label,
                is_active=bool(r.is_active),
                uploaded_at=r.uploaded_at,
            )
            for r in rows
        ]
    )


def update_master_resume(
    session: Session,
    user: User,
    resume_id: uuid.UUID,
    payload: MasterResumeUpdate,
) -> MasterResumeItem:
    resume = session.get(MasterResume, resume_id)
    if resume is None or resume.user_id != user.id:
        raise APIError(404, "Master resume not found", "NOT_FOUND")

    if payload.label is not None:
        resume.label = payload.label.strip() or None

    if payload.is_active is True:
        others = (
            session.query(MasterResume)
            .filter(MasterResume.user_id == user.id, MasterResume.id != resume.id)
            .all()
        )
        for other in others:
            other.is_active = False
        resume.is_active = True
    elif payload.is_active is False:
        resume.is_active = False

    resume.uploaded_at = resume.uploaded_at or datetime.now(timezone.utc)
    session.flush()
    return MasterResumeItem(
        id=str(resume.id),
        filename=resume.filename,
        label=resume.label,
        is_active=bool(resume.is_active),
        uploaded_at=resume.uploaded_at,
    )
