"""Background execution for manual per-user pipeline triggers."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import date, datetime, timezone

from db.engine import get_session
from db.models import PipelineRun, User
from pipeline.cancel import clear_pipeline_cancel
from pipeline.pipeline import PipelineAlreadyRunningError, run_nightly_pipeline

log = logging.getLogger(__name__)

_threads: dict[uuid.UUID, threading.Thread] = {}
_lock = threading.Lock()


def is_background_pipeline_running(user_id: uuid.UUID | None = None) -> bool:
    with _lock:
        if user_id is None:
            return any(t.is_alive() for t in _threads.values())
        thread = _threads.get(user_id)
        return thread is not None and thread.is_alive()


def _mark_stale_run_failed(user_id: uuid.UUID) -> None:
    """Mark today's run failed if the background thread died unexpectedly; refund tokens."""
    try:
        with get_session() as session:
            run = (
                session.query(PipelineRun)
                .filter_by(run_date=date.today(), user_id=user_id)
                .first()
            )
            if run is not None and run.status == "running" and run.completed_at is None:
                run.status = "failed"
                run.completed_at = datetime.now(timezone.utc)
                if not run.error_stage:
                    run.error_stage = run.current_stage
                if not run.error_message:
                    run.error_message = "Background pipeline thread exited unexpectedly"
                user = session.get(User, user_id)
                if user is not None:
                    from services.token_billing import refund_pipeline_run
                    from services.notifications.producers import enqueue_pipeline_status_notification

                    refund_pipeline_run(
                        session,
                        user,
                        run.id,
                        note="Pipeline thread exited — tokens refunded",
                    )
                    enqueue_pipeline_status_notification(session, user, run)
                session.commit()
    except Exception:
        log.exception("Failed to mark stale pipeline run as failed for %s", user_id)


def schedule_pipeline_run(
    user_id: uuid.UUID,
    *,
    resume_from: str | None = None,
) -> None:
    """Run the pipeline for one user in a background thread."""
    global _threads

    def _execute() -> None:
        clear_pipeline_cancel(user_id)
        try:
            log.info(
                "Background pipeline run starting for user=%s resume_from=%s",
                user_id,
                resume_from,
            )
            with get_session() as session:
                user = session.get(User, user_id)
                if user is None:
                    raise RuntimeError(f"User {user_id} not found")
                run = run_nightly_pipeline(session, user=user, resume_from=resume_from)
            log.info(
                "Background pipeline finished for user=%s status=%s",
                user_id,
                run.status,
            )
        except Exception:
            log.exception("Background pipeline run failed for user=%s", user_id)
            _mark_stale_run_failed(user_id)
        finally:
            clear_pipeline_cancel(user_id)
            with _lock:
                current = _threads.get(user_id)
                if current is threading.current_thread():
                    _threads.pop(user_id, None)

    with _lock:
        existing = _threads.get(user_id)
        if existing is not None and existing.is_alive():
            raise PipelineAlreadyRunningError("Pipeline is already running for this user")
        clear_pipeline_cancel(user_id)
        thread = threading.Thread(
            target=_execute,
            name=f"pipeline-run-{user_id}",
            daemon=True,
        )
        _threads[user_id] = thread
        thread.start()
