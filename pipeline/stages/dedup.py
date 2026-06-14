"""
Two-pass deduplication. No embeddings. No LLM.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from rapidfuzz import fuzz

from pipeline.sources.base import JobDict

log = logging.getLogger(__name__)

SOFT_DEDUP_THRESHOLD = 92.0


@dataclass
class DedupResult:
    """Output of the deduplication stage with metrics for pipeline logging."""

    jobs: list[JobDict]
    jobs_in: int
    jobs_out: int
    hard_removed: int
    soft_removed: int


def hard_dedup_key(job: JobDict) -> str:
    """SHA-256 of normalised company + title + country."""
    raw = (
        f"{job['company'].lower().strip()}|"
        f"{job['title'].lower().strip()}|"
        f"{(job.get('country') or '').lower().strip()}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def hard_dedup(jobs: list[JobDict]) -> list[JobDict]:
    """Remove exact duplicates by company + title + country."""
    kept: list[JobDict] = []
    key_to_index: dict[str, int] = {}

    for job in jobs:
        key = hard_dedup_key(job)
        if key not in key_to_index:
            key_to_index[key] = len(kept)
            kept.append(job)
            continue

        existing_index = key_to_index[key]
        existing = kept[existing_index]
        if len(job.get("description", "")) > len(existing.get("description", "")):
            kept[existing_index] = job

    return kept


def soft_dedup(jobs: list[JobDict], threshold: float = SOFT_DEDUP_THRESHOLD) -> list[JobDict]:
    """
    Compare pairs using rapidfuzz token_sort_ratio on company+title.
    If score >= threshold AND same country → keep the one with longer description.
    """
    kept: list[JobDict] = []
    for job in jobs:
        sig = f"{job['company']} {job['title']}"
        is_dup = False
        for index, existing in enumerate(kept):
            existing_sig = f"{existing['company']} {existing['title']}"
            score = fuzz.token_sort_ratio(sig, existing_sig)
            if score >= threshold and job.get("country") == existing.get("country"):
                if len(job.get("description", "")) > len(existing.get("description", "")):
                    kept[index] = job
                is_dup = True
                break
        if not is_dup:
            kept.append(job)
    return kept


def deduplicate(jobs: list[JobDict]) -> DedupResult:
    """Run hard then soft deduplication and return jobs with removal counts."""
    jobs_in = len(jobs)
    after_hard = hard_dedup(jobs)
    hard_removed = jobs_in - len(after_hard)
    after_soft = soft_dedup(after_hard)
    soft_removed = len(after_hard) - len(after_soft)

    log.info(
        "Dedup complete: in=%s hard_removed=%s soft_removed=%s out=%s",
        jobs_in,
        hard_removed,
        soft_removed,
        len(after_soft),
    )

    return DedupResult(
        jobs=after_soft,
        jobs_in=jobs_in,
        jobs_out=len(after_soft),
        hard_removed=hard_removed,
        soft_removed=soft_removed,
    )
