"""Authentication routes."""

from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import APIError, create_session_token, get_db
from api.schemas.user import AuthStatusResponse, LoginRequest, LoginResponse, SetupRequest
from db.models import User
from services.auth import create_user, has_any_users

router = APIRouter(prefix="/auth", tags=["auth"])


def _login_response(user: User) -> LoginResponse:
    token = create_session_token(user.id, user.email)
    return LoginResponse(
        token=token,
        user_id=str(user.id),
        name=user.name,
        email=user.email,
    )


def _register_and_login(payload: SetupRequest, db: Session) -> LoginResponse:
    user = create_user(db, name=payload.name, email=payload.email, password=payload.password)
    return _login_response(user)


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(db: Session = Depends(get_db)) -> AuthStatusResponse:
    """Report whether any dashboard users exist (public, no auth required)."""
    return AuthStatusResponse(has_users=has_any_users(db))


@router.post("/setup", response_model=LoginResponse)
def setup_first_user(payload: SetupRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Backward compatible route for creating a dashboard user."""
    return _register_and_login(payload, db)


@router.post("/register", response_model=LoginResponse)
def register(payload: SetupRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Create a new dashboard user (public, no auth required)."""
    return _register_and_login(payload, db)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Authenticate with email and password, returning a session token."""
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        raise APIError(401, "Invalid email or password", "AUTH_FAILED")

    if not bcrypt.checkpw(payload.password.encode(), user.dashboard_password.encode()):
        raise APIError(401, "Invalid email or password", "AUTH_FAILED")

    return _login_response(user)
