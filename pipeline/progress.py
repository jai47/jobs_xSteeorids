"""Persist pipeline progress for the dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from db.models import PipelineRun

MAX_LOG_ENTRIES = 300

STAGE_LABELS = {
    "starting": "Starting",
    "discover": "Discovering jobs",
    "deduplicate": "Deduplicating",
    "store_jobs": "Storing jobs",
    "score": "Scoring",
    "liveness": "Liveness checks",
    "company_universe": "Company universe",
    "legitimacy": "Legitimacy checks",
    "digest": "Daily digest",
    "skill_gap": "Skill gap report",
    "complete": "Complete",
}


def append_progress(
    session: Session,
    run: PipelineRun,
    *,
    stage: str,
    message: str,
    level: str = "info",
) -> None:
    """Append a log line and update the run's current stage."""
    run.current_stage = stage
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "level": level,
        "message": message,
    }
    logs = list(run.progress_log or [])
    logs.append(entry)
    if len(logs) > MAX_LOG_ENTRIES:
        logs = logs[-MAX_LOG_ENTRIES:]
    run.progress_log = logs
    session.commit()


def reset_progress(session: Session, run: PipelineRun) -> None:
    """Clear progress logs at the start of a run."""
    run.current_stage = "starting"
    run.progress_log = []
    session.commit()
