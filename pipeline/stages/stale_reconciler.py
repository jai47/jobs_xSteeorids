"""Mark board-sourced jobs stale when missing from consecutive discovery runs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models import Job

log = logging.getLogger(__name__)

# Full-board ATS sources — missing from a fetch means the posting likely closed.
BOARD_SOURCES = frozenset(
    {
        "greenhouse",
        "lever",
        "ashby",
        "workable",
        "smartrecruiters",
    }
)

STALE_AFTER_MISSES = 3


def reconcile_stale_jobs(
    session: Session,
    discovered_jobs: list[dict],
    *,
    stale_after_misses: int = STALE_AFTER_MISSES,
) -> dict[str, int]:
    """Bump miss counters for unseen board jobs; deactivate after N misses.

    Aggregator sources (Remotive, Adzuna, …) are ignored — a miss there only
    means the query set did not return the listing, not that it closed.
    """
    seen_by_source: dict[str, set[str]] = {}
    companies_by_source: dict[str, set[str]] = {}
    now = datetime.now(timezone.utc)

    for job in discovered_jobs:
        source = (job.get("source") or "").strip()
        if source not in BOARD_SOURCES:
            continue
        external_id = str(job.get("external_id") or "").strip()
        company = (job.get("company") or "").strip()
        if not external_id:
            continue
        seen_by_source.setdefault(source, set()).add(external_id)
        if company:
            companies_by_source.setdefault(source, set()).add(company.lower())

    if not seen_by_source:
        return {"checked": 0, "missed": 0, "deactivated": 0, "reactivated": 0}

    # Mark everything we saw this run as fresh.
    reactivated = 0
    for source, external_ids in seen_by_source.items():
        rows = (
            session.query(Job)
            .filter(Job.source == source, Job.external_id.in_(list(external_ids)))
            .all()
        )
        for row in rows:
            row.consecutive_misses = 0
            row.last_seen_at = now
            if not row.is_active or row.is_stale:
                row.is_active = True
                row.is_stale = False
                reactivated += 1

    checked = 0
    missed = 0
    deactivated = 0
    for source, companies in companies_by_source.items():
        seen_ids = seen_by_source.get(source, set())
        candidates = (
            session.query(Job)
            .filter(
                Job.source == source,
                Job.is_active.is_(True),
            )
            .all()
        )
        for row in candidates:
            if (row.company or "").lower() not in companies:
                continue
            if row.external_id in seen_ids:
                continue
            checked += 1
            missed += 1
            row.consecutive_misses = int(row.consecutive_misses or 0) + 1
            if row.consecutive_misses >= stale_after_misses:
                row.is_active = False
                row.is_stale = True
                deactivated += 1

    session.flush()
    log.info(
        "Stale reconcile: checked=%s missed=%s deactivated=%s reactivated=%s",
        checked,
        missed,
        deactivated,
        reactivated,
    )
    return {
        "checked": checked,
        "missed": missed,
        "deactivated": deactivated,
        "reactivated": reactivated,
    }
