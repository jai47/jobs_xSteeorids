"""STAR story CRUD and AI drafting."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from db.models import Application, Job, MasterResume, StarStory, User
from llm.client import call_llm
from services.llm_generation_guard import enforce_daily_generation_guard
from skills.star_tags import validate_tags

log = logging.getLogger(__name__)

PAGE_SIZE = 20


def story_to_dict(story: StarStory) -> dict:
    return {
        "id": str(story.id),
        "status": story.status,
        "title": story.title,
        "tags": list(story.tags or []),
        "situation": story.situation,
        "task": story.task,
        "action": story.action,
        "result": story.result,
        "reflection": story.reflection,
        "source_job_id": str(story.source_job_id) if story.source_job_id else None,
        "ai_drafted": bool(story.ai_drafted),
        "created_at": story.created_at,
        "updated_at": story.updated_at,
    }


def list_stories(
    session: Session,
    user: User,
    *,
    tag: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> tuple[list[StarStory], int]:
    query = session.query(StarStory).filter(StarStory.user_id == user.id)
    if tag:
        query = query.filter(StarStory.tags.contains([tag]))
    if status:
        query = query.filter(StarStory.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                StarStory.title.ilike(like),
                StarStory.situation.ilike(like),
                StarStory.action.ilike(like),
            )
        )
    total = query.count()
    offset = max(page - 1, 0) * page_size
    rows = (
        query.order_by(StarStory.updated_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return rows, total


def get_story(session: Session, user: User, story_id: uuid.UUID) -> StarStory:
    story = session.get(StarStory, story_id)
    if story is None or story.user_id != user.id:
        raise APIError(404, "Story not found", "NOT_FOUND")
    return story


def create_story(
    session: Session,
    user: User,
    *,
    title: str,
    tags: list[str],
    situation: str | None = None,
    task: str | None = None,
    action: str | None = None,
    result: str | None = None,
    reflection: str | None = None,
    status: str = "draft",
    source_job_id: uuid.UUID | None = None,
) -> StarStory:
    try:
        validated = validate_tags(tags)
    except ValueError as exc:
        raise APIError(422, str(exc), "VALIDATION_ERROR") from exc
    if status not in {"draft", "ready"}:
        raise APIError(422, "Invalid status", "VALIDATION_ERROR")
    story = StarStory(
        user_id=user.id,
        title=title.strip(),
        tags=validated,
        situation=situation,
        task=task,
        action=action,
        result=result,
        reflection=reflection,
        status=status,
        source_job_id=source_job_id,
        ai_drafted=False,
    )
    session.add(story)
    session.flush()
    return story


def update_story(
    session: Session,
    user: User,
    story_id: uuid.UUID,
    **fields,
) -> StarStory:
    story = get_story(session, user, story_id)
    if "tags" in fields and fields["tags"] is not None:
        try:
            fields["tags"] = validate_tags(fields["tags"])
        except ValueError as exc:
            raise APIError(422, str(exc), "VALIDATION_ERROR") from exc
    if "status" in fields and fields["status"] not in {None, "draft", "ready"}:
        raise APIError(422, "Invalid status", "VALIDATION_ERROR")
    for key, value in fields.items():
        if value is not None and hasattr(story, key):
            setattr(story, key, value)
    story.updated_at = datetime.now(timezone.utc)
    session.flush()
    return story


def delete_story(session: Session, user: User, story_id: uuid.UUID) -> None:
    story = get_story(session, user, story_id)
    session.delete(story)
    session.flush()


def _resume_highlights(session: Session, user: User) -> str:
    master = (
        session.query(MasterResume)
        .filter_by(user_id=user.id, is_active=True)
        .order_by(MasterResume.uploaded_at.desc())
        .first()
    )
    if master and master.raw_text:
        return master.raw_text[:4000]
    return ""


def ai_draft_story(
    session: Session,
    user: User,
    *,
    tag: str,
    application_id: uuid.UUID | None = None,
) -> StarStory:
    enforce_daily_generation_guard(session, user.id)
    try:
        validated = validate_tags([tag])
    except ValueError as exc:
        raise APIError(422, str(exc), "VALIDATION_ERROR") from exc
    tag_name = validated[0]

    job_context = ""
    source_job_id = None
    if application_id:
        app = session.get(Application, application_id)
        if app is None or app.user_id != user.id:
            raise APIError(404, "Application not found", "NOT_FOUND")
        job = session.get(Job, app.job_id)
        if job:
            source_job_id = job.id
            job_context = f"Role: {job.title} at {job.company}\n{(job.description or '')[:2000]}"

    resume = _resume_highlights(session, user)
    prompt = f"""Draft a STAR interview story for the behavioral theme "{tag_name}".
Use ONLY facts from the resume below. Do not invent employers, dates, or metrics.
Return plain text with labeled sections:
Title: (one line)
Situation: ...
Task: ...
Action: ...
Result: ...
Reflection: ...

Resume:
{resume}

{f"Job context:{chr(10)}{job_context}" if job_context else ""}
"""
    try:
        raw = call_llm(prompt, "star_themes", user.id, session, max_tokens=1200)
    except LLMError as exc:
        raise APIError(502, str(exc), "LLM_ERROR") from exc

    title = f"Story: {tag_name.replace('_', ' ').title()}"
    sections = {"situation": "", "task": "", "action": "", "result": "", "reflection": ""}
    current = None
    for line in raw.splitlines():
        lower = line.strip().lower()
        if lower.startswith("title:"):
            title = line.split(":", 1)[1].strip() or title
            current = None
        elif lower.startswith("situation:"):
            current = "situation"
            sections[current] = line.split(":", 1)[1].strip()
        elif lower.startswith("task:"):
            current = "task"
            sections[current] = line.split(":", 1)[1].strip()
        elif lower.startswith("action:"):
            current = "action"
            sections[current] = line.split(":", 1)[1].strip()
        elif lower.startswith("result:"):
            current = "result"
            sections[current] = line.split(":", 1)[1].strip()
        elif lower.startswith("reflection:"):
            current = "reflection"
            sections[current] = line.split(":", 1)[1].strip()
        elif current:
            sections[current] = (sections[current] + "\n" + line).strip()

    story = create_story(
        session,
        user,
        title=title,
        tags=[tag_name],
        situation=sections["situation"] or None,
        task=sections["task"] or None,
        action=sections["action"] or None,
        result=sections["result"] or None,
        reflection=sections["reflection"] or None,
        status="draft",
        source_job_id=source_job_id,
    )
    story.ai_drafted = True
    session.flush()
    return story
