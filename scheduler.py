"""APScheduler setup for nightly pipeline runs and notification jobs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from db.engine import get_session
from pipeline.pipeline import run_nightly_pipeline
from services.notifications.drainer import drain_notification_outbox
from services.notifications.follow_up_scanner import scan_follow_ups

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _execute_pipeline() -> None:
    """Run the nightly pipeline for each user individually."""
    log.info("Starting scheduled nightly pipeline (per user)")
    try:
        with get_session() as session:
            run = run_nightly_pipeline(session, user=None)
        log.info("Nightly pipeline batch finished with last status=%s", run.status)
    except Exception:
        log.exception("Scheduled pipeline run failed")


def _drain_notifications() -> None:
    try:
        with get_session() as session:
            count = drain_notification_outbox(session)
            session.commit()
        if count:
            log.info("Drained %d email notifications", count)
    except Exception:
        log.exception("Notification drain failed")


def _scan_follow_ups() -> None:
    try:
        with get_session() as session:
            count = scan_follow_ups(session)
            session.commit()
        log.info("Follow-up scan enqueued %d in-app notifications", count)
    except Exception:
        log.exception("Follow-up scan failed")


def start_scheduler() -> None:
    """Start APScheduler with pipeline, notification drain, and follow-up jobs."""
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
    scheduler.add_job(
        _drain_notifications,
        trigger=IntervalTrigger(minutes=settings.notification_drain_interval_min),
        id="notification_drain",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        _scan_follow_ups,
        trigger=CronTrigger(hour=settings.pipeline_cron_hour, minute=30),
        id="follow_up_scan",
        max_instances=1,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.start()
    log.info(
        "Scheduler started (pipeline hour=%s, drain every %sm)",
        settings.pipeline_cron_hour,
        settings.notification_drain_interval_min,
    )


def shutdown_scheduler() -> None:
    """Shut down APScheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("Scheduler shut down")
