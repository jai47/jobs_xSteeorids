"""APScheduler setup for nightly pipeline runs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from db.engine import get_session
from pipeline.pipeline import run_nightly_pipeline

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _execute_pipeline() -> None:
    """Run the nightly pipeline inside a DB session."""
    log.info("Starting scheduled nightly pipeline")
    try:
        with get_session() as session:
            run = run_nightly_pipeline(session)
        log.info("Pipeline finished with status=%s", run.status)
    except Exception:
        log.exception("Scheduled pipeline run failed")


def start_scheduler() -> None:
    """Start APScheduler with the nightly pipeline cron job."""
    if scheduler.running:
        return
    scheduler.add_job(
        _execute_pipeline,
        trigger=CronTrigger(hour=settings.pipeline_cron_hour, minute=0),
        id="nightly_pipeline",
        max_instances=1,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.start()
    log.info("Scheduler started (pipeline cron hour=%s)", settings.pipeline_cron_hour)


def shutdown_scheduler() -> None:
    """Shut down APScheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("Scheduler shut down")
