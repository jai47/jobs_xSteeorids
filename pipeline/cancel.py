"""Cooperative cancel signals scoped per user (multi-tenant safe)."""

from __future__ import annotations

import threading
import uuid

_lock = threading.Lock()
_cancel_events: dict[uuid.UUID, threading.Event] = {}
# Backward-compatible global flag used only when no user_id is supplied.
_legacy_cancel = threading.Event()


class PipelineCancelled(Exception):
    """Raised when a pipeline run is stopped by user request."""


def _event_for(user_id: uuid.UUID | None) -> threading.Event:
    if user_id is None:
        return _legacy_cancel
    with _lock:
        event = _cancel_events.get(user_id)
        if event is None:
            event = threading.Event()
            _cancel_events[user_id] = event
        return event


def is_cancel_requested(user_id: uuid.UUID | None = None) -> bool:
    return _event_for(user_id).is_set()


def request_pipeline_cancel(user_id: uuid.UUID | None = None) -> None:
    _event_for(user_id).set()


def clear_pipeline_cancel(user_id: uuid.UUID | None = None) -> None:
    event = _event_for(user_id)
    event.clear()
    if user_id is not None:
        with _lock:
            # Drop empty events so the map does not grow unbounded.
            if user_id in _cancel_events and not _cancel_events[user_id].is_set():
                _cancel_events.pop(user_id, None)
