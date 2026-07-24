"""Shared helpers for application.autopilot / user.autopilot JSON blobs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from db.models import Application, User


def get_app_autopilot(application: Application) -> dict[str, Any]:
    raw = application.autopilot
    return dict(raw) if isinstance(raw, dict) else {}


def set_app_autopilot(application: Application, data: dict[str, Any]) -> None:
    application.autopilot = deepcopy(data)


def patch_app_autopilot(application: Application, **kwargs: Any) -> dict[str, Any]:
    data = get_app_autopilot(application)
    data.update(kwargs)
    set_app_autopilot(application, data)
    return data


def get_user_autopilot(user: User) -> dict[str, Any]:
    raw = user.autopilot
    return dict(raw) if isinstance(raw, dict) else {}


def patch_user_autopilot(user: User, **kwargs: Any) -> dict[str, Any]:
    data = get_user_autopilot(user)
    data.update(kwargs)
    user.autopilot = deepcopy(data)
    return data
