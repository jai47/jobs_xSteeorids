"""Seed first admin user from SEED_USER_* env vars."""

from __future__ import annotations

import logging

from db.engine import get_session
from db.models import User
from services.auth import create_user
from config import settings

log = logging.getLogger(__name__)


def seed_admin_user_if_configured() -> None:
    email = (settings.seed_user_email or "").strip().lower()
    password = settings.seed_user_password or ""
    name = (settings.seed_user_name or "Admin").strip() or "Admin"
    if not email or not password:
        return
    if len(password) < 8:
        log.warning("SEED_USER_PASSWORD too short; skipping admin seed")
        return

    try:
        with get_session() as session:
            existing = session.query(User).filter(User.email == email).first()
            if existing is not None:
                if not existing.is_admin:
                    existing.is_admin = True
                    session.commit()
                    log.info("Marked existing seed user as admin: %s", email)
                return
            user = create_user(session, name=name, email=email, password=password, is_admin=True)
            session.commit()
            log.info("Seeded admin user %s", email)
    except Exception:
        log.exception("Failed to seed admin user")
