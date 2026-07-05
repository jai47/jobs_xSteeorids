"""STAR story bank routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.story import (
    StoryCreate,
    StoryDraftRequest,
    StoryListResponse,
    StoryResponse,
    StoryUpdate,
)
from db.models import User
from services.star_stories import (
    ai_draft_story,
    create_story,
    delete_story,
    get_story,
    list_stories,
    story_to_dict,
    update_story,
)

router = APIRouter(prefix="/stories", tags=["stories"])


def _story_response(story) -> StoryResponse:
    return StoryResponse(**story_to_dict(story))


@router.get("", response_model=StoryListResponse)
def get_stories(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    tag: str | None = None,
    status: str | None = Query(default=None),
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> StoryListResponse:
    rows, total = list_stories(db, user, tag=tag, status=status, q=q, page=page, page_size=page_size)
    return StoryListResponse(items=[_story_response(r) for r in rows], total=total)


@router.post("", response_model=StoryResponse, status_code=status.HTTP_201_CREATED)
def post_story(
    payload: StoryCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StoryResponse:
    story = create_story(
        db,
        user,
        title=payload.title,
        tags=payload.tags,
        situation=payload.situation,
        task=payload.task,
        action=payload.action,
        result=payload.result,
        reflection=payload.reflection,
        status=payload.status,
    )
    return _story_response(story)


@router.put("/{story_id}", response_model=StoryResponse)
def put_story(
    story_id: uuid.UUID,
    payload: StoryUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StoryResponse:
    story = update_story(db, user, story_id, **payload.model_dump(exclude_unset=True))
    return _story_response(story)


@router.delete("/{story_id}", status_code=204)
def remove_story(
    story_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    delete_story(db, user, story_id)
    return Response(status_code=204)


@router.post("/draft", response_model=StoryResponse, status_code=status.HTTP_201_CREATED)
def draft_story(
    payload: StoryDraftRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StoryResponse:
    app_id = uuid.UUID(payload.application_id) if payload.application_id else None
    story = ai_draft_story(db, user, tag=payload.tag, application_id=app_id)
    return _story_response(story)
