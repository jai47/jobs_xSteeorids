"""Build and persist resume + jobs context for LLM coaching prompts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Job, MasterResume, ScoredOpportunity, SkillGapReport, User, UserLlmContext
from pipeline.stages.overall_scorer import DIGEST_MIN_SCORE, is_digest_eligible
from pipeline.role_targets import build_role_profile_for_user

log = logging.getLogger(__name__)

RESUME_RAW_MAX = 3500
JOBS_LIMIT = 25
JOB_DESC_MAX = 280
CONTEXT_TEXT_MAX = 9000


def _active_master(session: Session, user: User) -> MasterResume | None:
    return session.scalar(
        select(MasterResume)
        .where(MasterResume.user_id == user.id, MasterResume.is_active.is_(True))
        .order_by(MasterResume.uploaded_at.desc())
        .limit(1)
    )


def _summarize_resume(user: User, master: MasterResume | None) -> str:
    lines: list[str] = [
        f"Candidate: {user.name}",
        f"Email: {user.email}",
    ]
    if user.years_experience is not None:
        lines.append(f"Years of experience: {user.years_experience}")
    if user.preferred_roles:
        lines.append(f"Preferred roles: {', '.join(user.preferred_roles)}")
    if user.preferred_countries:
        lines.append(f"Preferred countries: {', '.join(user.preferred_countries)}")
    if user.prefers_remote:
        lines.append("Prefers remote roles")
    skills = list(user.parsed_skills or [])
    if master and isinstance(master.parsed_json, dict):
        parsed = master.parsed_json
        if not skills:
            skills = list(parsed.get("skills") or [])
        titles = list(parsed.get("previous_titles") or [])
        if titles:
            lines.append(f"Previous titles: {', '.join(titles[:12])}")
        education = list(parsed.get("education") or [])
        if education:
            lines.append(f"Education: {', '.join(str(e) for e in education[:6])}")
        languages = list(parsed.get("languages") or [])
        if languages:
            lines.append(f"Languages: {', '.join(str(l) for l in languages[:8])}")
    if skills:
        lines.append(f"Skills: {', '.join(skills[:40])}")

    if master and (master.raw_text or "").strip():
        raw = " ".join((master.raw_text or "").split())
        lines.append("")
        lines.append("Resume excerpt:")
        lines.append(raw[:RESUME_RAW_MAX])
    elif not master:
        lines.append("No active master resume uploaded yet.")

    return "\n".join(lines).strip()


def _jobs_snapshot(session: Session, user: User, *, limit: int = JOBS_LIMIT) -> list[dict[str, Any]]:
    role_profile = build_role_profile_for_user(session, user)
    rows = (
        session.query(ScoredOpportunity, Job)
        .join(Job, Job.id == ScoredOpportunity.job_id)
        .filter(
            ScoredOpportunity.user_id == user.id,
            ScoredOpportunity.overall_score >= DIGEST_MIN_SCORE,
            ScoredOpportunity.user_feedback.is_(None),
        )
        .order_by(ScoredOpportunity.overall_score.desc())
        .limit(limit * 2)
        .all()
    )
    out: list[dict[str, Any]] = []
    for opp, job in rows:
        if not is_digest_eligible(
            float(opp.overall_score or 0),
            score_role_match=opp.score_role_match,
            has_role_preference=role_profile.has_role_preference,
        ):
            continue
        desc = " ".join((job.description or "").split())
        out.append(
            {
                "opportunity_id": str(opp.id),
                "job_id": str(job.id),
                "title": job.title,
                "company": job.company,
                "country": job.country,
                "remote_type": job.remote_type,
                "salary_display": job.salary_display,
                "overall_score": opp.overall_score,
                "classification": opp.classification,
                "visa_status": opp.visa_status,
                "skills_required": list(job.skills_required or [])[:12],
                "url": job.url,
                "description_excerpt": desc[:JOB_DESC_MAX] if desc else None,
                "fit_reasoning": (opp.fit_reasoning or "")[:220] or None,
            }
        )
        if len(out) >= limit:
            break
    return out


def _skill_gaps_line(session: Session, user: User) -> str | None:
    report = (
        session.query(SkillGapReport)
        .filter_by(user_id=user.id)
        .order_by(SkillGapReport.created_at.desc())
        .first()
    )
    if report is None:
        return None
    raw = list(report.top_missing_skills or [])[:15]
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            skill = item.get("skill")
            if skill:
                names.append(str(skill))
        elif item:
            names.append(str(item))
    if not names:
        return None
    return f"Recent skill gaps vs market: {', '.join(names)}"


def _assemble_context_text(
    *,
    resume_summary: str,
    jobs: list[dict[str, Any]],
    skill_gaps_line: str | None,
) -> str:
    parts = ["=== CANDIDATE RESUME CONTEXT ===", resume_summary, "", "=== MATCHED JOBS (scored) ==="]
    if not jobs:
        parts.append("No scored opportunities yet. Run the pipeline after uploading a resume.")
    else:
        for i, job in enumerate(jobs, start=1):
            skills = ", ".join(job.get("skills_required") or []) or "n/a"
            line = (
                f"{i}. {job.get('title')} @ {job.get('company')} "
                f"(score={job.get('overall_score')}, {job.get('classification')}, "
                f"{job.get('country') or 'n/a'}, {job.get('remote_type') or 'n/a'})"
            )
            parts.append(line)
            parts.append(f"   Skills: {skills}")
            if job.get("description_excerpt"):
                parts.append(f"   JD: {job['description_excerpt']}")
            if job.get("fit_reasoning"):
                parts.append(f"   Fit: {job['fit_reasoning']}")
            if job.get("url"):
                parts.append(f"   URL: {job['url']}")
    if skill_gaps_line:
        parts.extend(["", "=== SKILL GAPS ===", skill_gaps_line])
    text = "\n".join(parts).strip()
    return text[:CONTEXT_TEXT_MAX]


def get_user_llm_context(session: Session, user: User) -> UserLlmContext | None:
    return session.scalar(select(UserLlmContext).where(UserLlmContext.user_id == user.id))


def rebuild_user_llm_context(session: Session, user: User) -> UserLlmContext:
    """Create or refresh the persisted resume + jobs context for this user."""
    master = _active_master(session, user)
    resume_summary = _summarize_resume(user, master)
    jobs = _jobs_snapshot(session, user)
    skill_gaps_line = _skill_gaps_line(session, user)
    context_text = _assemble_context_text(
        resume_summary=resume_summary,
        jobs=jobs,
        skill_gaps_line=skill_gaps_line,
    )
    now = datetime.now(timezone.utc)
    row = get_user_llm_context(session, user)
    if row is None:
        row = UserLlmContext(user_id=user.id)
        session.add(row)
        row.built_at = now
    row.master_resume_id = master.id if master else None
    row.resume_summary = resume_summary
    row.jobs_snapshot = jobs
    row.context_text = context_text
    row.updated_at = now
    session.flush()
    log.info(
        "Rebuilt LLM context for user=%s resume=%s jobs=%d chars=%d",
        user.id,
        master.id if master else None,
        len(jobs),
        len(context_text),
    )
    return row


def ensure_user_llm_context(session: Session, user: User) -> UserLlmContext:
    """Return existing context, rebuilding if missing or resume changed."""
    row = get_user_llm_context(session, user)
    master = _active_master(session, user)
    master_id = master.id if master else None
    if row is None or row.master_resume_id != master_id or not (row.context_text or "").strip():
        return rebuild_user_llm_context(session, user)
    return row


def career_context_for_prompt(session: Session, user: User, *, max_chars: int = 7000) -> str:
    """Prompt-ready career context string (resume + jobs), ensuring a row exists."""
    row = ensure_user_llm_context(session, user)
    return (row.context_text or "")[:max_chars]
