"""Create tailored resume versions on opportunity approval."""

from __future__ import annotations

from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import Job, MasterResume, ResumeVersion, User
from llm.resume_tailor import tailor_resume_for_job


def get_active_master_resume(session: Session, user: User) -> MasterResume:
    """Return the user's active master resume or raise if missing."""
    master = (
        session.query(MasterResume)
        .filter_by(user_id=user.id, is_active=True)
        .order_by(MasterResume.uploaded_at.desc())
        .first()
    )
    if master is None or not (master.raw_text or "").strip():
        raise APIError(
            400,
            "Upload a master resume before approving opportunities",
            "VALIDATION_ERROR",
        )
    return master


def create_tailored_resume_version(
    session: Session,
    user: User,
    job: Job,
    master: MasterResume,
) -> ResumeVersion:
    """Run LLM tailoring and persist a resume_versions row."""
    output = tailor_resume_for_job(
        master.raw_text or "",
        job.description or "",
        user.id,
        session,
    )
    version = ResumeVersion(
        job_id=job.id,
        user_id=user.id,
        master_resume_id=master.id,
        ats_score_before=output.ats_score_before,
        ats_score_after=output.ats_score_after,
        keywords_added=output.keywords_added,
        skill_gaps=output.skill_gaps,
        tailored_markdown=output.tailored_markdown,
        json_resume=output.json_resume,
    )
    session.add(version)
    session.flush()
    return version
