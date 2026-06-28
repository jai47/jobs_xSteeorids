"""Authentication helpers for user creation and status checks."""

from __future__ import annotations

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import User


def has_any_users(session: Session) -> bool:
    """Return whether at least one dashboard user exists."""
    count = session.scalar(select(func.count()).select_from(User))
    return bool(count)


def create_user(session: Session, *, name: str, email: str, password: str) -> User:
    """Create a new dashboard user with a bcrypt-hashed password."""
    normalized_email = email.strip().lower()
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = User(
        name=name.strip(),
        email=normalized_email,
        dashboard_password=password_hash,
    )
    session.add(user)
    session.flush()
    return user
