"""Background execution for manual pipeline triggers."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone

from db.engine import get_session
from db.models import PipelineRun
from pipeline.cancel import clear_pipeline_cancel
from pipeline.pipeline import PipelineAlreadyRunningError, run_nightly_pipeline

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_lock = threading.Lock()


def is_background_pipeline_running() -> bool:
    with _lock:
        return _thread is not None and _thread.is_alive()


def _mark_stale_run_failed() -> None:
    """Mark today's run failed if the background thread died unexpectedly."""
    try:
        with get_session() as session:
            run = session.query(PipelineRun).filter_by(run_date=date.today()).first()
            if run is not None and run.status == "running" and run.completed_at is None:
                run.status = "failed"
                run.completed_at = datetime.now(timezone.utc)
                if not run.error_message:
                    run.error_message = "Background pipeline thread exited unexpectedly"
                session.commit()
    except Exception:
        log.exception("Failed to mark stale pipeline run as failed")


def schedule_pipeline_run() -> None:
    """Run the nightly pipeline in a background thread."""
    global _thread

    def _execute() -> None:
        global _thread
        clear_pipeline_cancel()
        try:
            log.info("Background pipeline run starting")
            with get_session() as session:
                run = run_nightly_pipeline(session)
            log.info("Background pipeline finished with status=%s", run.status)
        except Exception:
            log.exception("Background pipeline run failed")
            _mark_stale_run_failed()
        finally:
            clear_pipeline_cancel()
            with _lock:
                _thread = None

    with _lock:
        if _thread is not None and _thread.is_alive():
            raise PipelineAlreadyRunningError("Pipeline is already running")
        clear_pipeline_cancel()
        _thread = threading.Thread(target=_execute, name="pipeline-run", daemon=True)
        _thread.start()
