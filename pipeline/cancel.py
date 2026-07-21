"""Cooperative cancel signal shared by pipeline orchestrator and runner."""

from __future__ import annotations

import threading

_cancel_event = threading.Event()


class PipelineCancelled(Exception):
    """Raised when a pipeline run is stopped by user request."""


def is_cancel_requested() -> bool:
    return _cancel_event.is_set()


def request_pipeline_cancel() -> None:
    _cancel_event.set()


def clear_pipeline_cancel() -> None:
    _cancel_event.clear()
