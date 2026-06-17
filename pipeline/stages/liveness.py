"""
Async liveness check. HEAD requests to job URLs.
Runs in background after pipeline scoring completes.
Stale jobs are flagged, not dropped.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import Job

log = logging.getLogger(__name__)

MAX_CONCURRENT_CHECKS = 10
HEAD_TIMEOUT_SECONDS = 10.0

HOMEPAGE_PATHS = {
    "",
    "/",
    "/careers",
    "/jobs",
    "/openings",
    "/join-us",
    "/work-with-us",
}


def _is_homepage(url: str) -> bool:
    """Return True when a redirect target looks like a careers/homepage URL."""
    path = urlparse(url).path.rstrip("/").lower()
    return path in HOMEPAGE_PATHS


def get_jobs_to_verify(session: Session) -> list[Job]:
    """Jobs to check: active jobs not verified in the last 14 days."""
    cutoff = date.today() - timedelta(days=14)
    return (
        session.query(Job)
        .filter(
            Job.is_active.is_(True),
            (Job.last_verified.is_(None)) | (Job.last_verified < cutoff),
        )
        .all()
    )


async def _check_one(
    client: httpx.AsyncClient,
    job: Job,
    semaphore: asyncio.Semaphore,
) -> tuple[int, str]:
    """Issue one HEAD request and return status code plus resolved URL."""
    async with semaphore:
        response = await client.head(job.url)
        final_url = str(response.url)
        if response.status_code in (301, 302, 307, 308):
            location = response.headers.get("location")
            if location:
                final_url = urljoin(job.url, location)
        return response.status_code, final_url


async def verify_liveness(session: Session, jobs_to_check: list[Job]) -> None:
    """Check job URLs asynchronously and update DB flags."""
    if not jobs_to_check:
        return

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    async with httpx.AsyncClient(timeout=HEAD_TIMEOUT_SECONDS, follow_redirects=False) as client:
        tasks = [_check_one(client, job, semaphore) for job in jobs_to_check]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    today = date.today()
    for job, result in zip(jobs_to_check, results):
        if isinstance(result, Exception):
            log.warning("Liveness check failed for job %s: %s", job.id, result)
            continue

        status_code, final_url = result
        if status_code in (404, 410):
            job.is_active = False
            job.is_stale = True
        elif status_code == 200:
            job.last_verified = today
            job.is_stale = False
        elif status_code in (301, 302, 307, 308) and _is_homepage(final_url):
            job.is_active = False
            job.is_stale = True

    session.commit()
    log.info("Liveness verification updated %s jobs", len(jobs_to_check))


async def run_liveness_checks(job_ids: list[uuid.UUID]) -> None:
    """Load jobs in a fresh session and verify liveness."""
    if not job_ids:
        return
    try:
        with get_session() as session:
            jobs = session.query(Job).filter(Job.id.in_(job_ids)).all()
            await verify_liveness(session, jobs)
    except Exception:
        log.exception("Background liveness verification failed")


def schedule_liveness_verification(session: Session) -> None:
    """Start liveness checks without blocking the pipeline."""
    jobs = get_jobs_to_verify(session)
    if not jobs:
        return

    job_ids = [job.id for job in jobs]
    log.info("Scheduling liveness verification for %s jobs", len(job_ids))

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        thread = threading.Thread(
            target=lambda: asyncio.run(run_liveness_checks(job_ids)),
            name="liveness-verification",
            daemon=True,
        )
        thread.start()
        return

    loop.create_task(run_liveness_checks(job_ids))
