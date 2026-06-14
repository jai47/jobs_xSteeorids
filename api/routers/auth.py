"""Authentication routes."""

from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import APIError, create_session_token, get_db
from api.schemas.user import LoginRequest, LoginResponse
from db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Authenticate with email and password, returning a session token."""
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        raise APIError(401, "Invalid email or password", "AUTH_FAILED")

    if not bcrypt.checkpw(payload.password.encode(), user.dashboard_password.encode()):
        raise APIError(401, "Invalid email or password", "AUTH_FAILED")

    token = create_session_token(user.id, user.email)
    return LoginResponse(
        token=token,
        user_id=str(user.id),
        name=user.name,
        email=user.email,
    )
