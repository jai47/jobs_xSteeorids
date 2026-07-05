"""Deterministic interview prep — rank stories by tag overlap."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import Application, StarStory, User
from services.star_stories import story_to_dict
from services.theme_extraction import get_themes_for_application

MAX_STORIES = 3


def rank_stories_for_themes(stories: list[StarStory], themes: list[str]) -> list[StarStory]:
    theme_set = set(themes)

    def score(story: StarStory) -> tuple[int, float]:
        overlap = len(theme_set.intersection(set(story.tags or [])))
        updated = story.updated_at.timestamp() if story.updated_at else 0.0
        return (overlap, updated)

    ready = [s for s in stories if s.status == "ready"]
    ranked = sorted(ready, key=score, reverse=True)
    return ranked[:MAX_STORIES]


def interview_prep(session: Session, user: User, application_id: uuid.UUID) -> dict:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")

    theme_row = get_themes_for_application(session, application_id)
    themes = list(theme_row.themes or []) if theme_row and theme_row.status == "ready" else []

    all_stories = (
        session.query(StarStory)
        .filter_by(user_id=user.id)
        .order_by(StarStory.updated_at.desc())
        .all()
    )
    top_stories = rank_stories_for_themes(all_stories, themes)
    covered = set()
    for story in top_stories:
        covered.update(story.tags or [])
    uncovered = [t for t in themes if t not in covered]

    return {
        "themes": themes,
        "stories": [story_to_dict(s) for s in top_stories],
        "uncovered_themes": uncovered,
    }
