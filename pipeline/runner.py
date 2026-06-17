"""Background execution for manual pipeline triggers."""

from __future__ import annotations

import logging
import threading

from db.engine import get_session
from pipeline.pipeline import PipelineAlreadyRunningError, run_nightly_pipeline

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_lock = threading.Lock()


def is_background_pipeline_running() -> bool:
    with _lock:
        return _thread is not None and _thread.is_alive()


def schedule_pipeline_run() -> None:
    """Run the nightly pipeline in a background thread."""
    global _thread

    def _execute() -> None:
        global _thread
        try:
            log.info("Background pipeline run starting")
            with get_session() as session:
                run = run_nightly_pipeline(session)
            log.info("Background pipeline finished with status=%s", run.status)
        except Exception:
            log.exception("Background pipeline run failed")
        finally:
            with _lock:
                _thread = None

    with _lock:
        if _thread is not None and _thread.is_alive():
            raise PipelineAlreadyRunningError("Pipeline is already running")
        _thread = threading.Thread(target=_execute, name="pipeline-run", daemon=True)
        _thread.start()
