"""
G8 — cross-time repost detection at store stage.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from db.models import Job
from pipeline.stages.dedup import hard_dedup_key
from pipeline.sources.base import JobDict


def job_fingerprint(job: JobDict | Job) -> str:
    """SHA-256 fingerprint from normalised company+title+country."""
    if isinstance(job, Job):
        payload: JobDict = {
            "company": job.company,
            "title": job.title,
            "country": job.country,
        }
    else:
        payload = job
    return hard_dedup_key(payload)


def description_hash(description: str | None) -> str | None:
    if not description:
        return None
    return hashlib.md5(description.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RepostMatch:
    original_job_id: object
    first_seen: date
    repost_count: int


def find_repost(
    session: Session,
    *,
    fingerprint: str,
    description: str | None,
    source: str,
    posted_at: date | None,
    exclude_job_id: object | None = None,
    window_days: int = 90,
    gap_days: int = 14,
) -> RepostMatch | None:
    """
    Find a prior job with the same fingerprint within the window.
    Returns None if description hash differs materially (treated as new posting).
    """
    cutoff = date.today() - timedelta(days=window_days)
    desc_hash = description_hash(description)

    candidates = (
        session.query(Job)
        .filter(
            Job.dedup_fingerprint == fingerprint,
            Job.created_at >= cutoff,
        )
        .order_by(Job.created_at.asc())
        .all()
    )
    if exclude_job_id is not None:
        candidates = [c for c in candidates if str(c.id) != str(exclude_job_id)]
    if not candidates:
        return None

    original = candidates[0]
    if desc_hash and original.description_hash and desc_hash != original.description_hash:
        return None

    # Same source and recent posting — not a repost.
    if posted_at and original.posted_at:
        gap = abs((posted_at - original.posted_at).days)
        if original.source == source and gap <= gap_days:
            return None

    if len(candidates) == 1 and str(original.id) == str(exclude_job_id or ""):
        return None

    repost_count = len(candidates)
    first_seen = original.posted_at or (original.created_at.date() if original.created_at else date.today())
    return RepostMatch(
        original_job_id=original.id,
        first_seen=first_seen,
        repost_count=repost_count,
    )
