"""HMAC unsubscribe tokens for email channels."""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from config import settings


def create_unsubscribe_token(user_id: uuid.UUID, channel: str) -> str:
    """channel: digest | followup"""
    payload = f"{user_id}:{channel}"
    sig = hmac.new(
        settings.dashboard_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_unsubscribe_token(token: str) -> tuple[uuid.UUID, str]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        user_part, channel, signature = decoded.rsplit(":", 2)
        user_id = uuid.UUID(user_part)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid token") from exc

    expected = hmac.new(
        settings.dashboard_secret.encode(),
        f"{user_id}:{channel}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid token")
    if channel not in {"digest", "followup"}:
        raise ValueError("Invalid channel")
    return user_id, channel


def build_unsubscribe_url(user_id: str | uuid.UUID, channel: str) -> str:
    uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    token = create_unsubscribe_token(uid, channel)
    base = settings.api_base_url.rstrip("/")
    return f"{base}/notifications/unsubscribe?token={token}"
