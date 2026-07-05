"""
F07 — ghost-job legitimacy heuristics (display-only, never affects score).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import re

from db.models import Job

RULE_VERSION = 1

_SCAM_PATTERNS = [
    (re.compile(r"\bguaranteed\s+income\b", re.I), "guaranteed income language"),
    (re.compile(r"\bregistration fee\b|\bupfront fee\b", re.I), "fees requested"),
    (re.compile(r"\bwhatsapp only\b|\bcontact via whatsapp\b", re.I), "WhatsApp-only contact"),
    (
        re.compile(
            r"\bno experience\b.*\b(senior|lead|principal|staff)\b|"
            r"\b(senior|lead|principal|staff)\b.*\bno experience\b",
            re.I,
        ),
        "no experience + senior title",
    ),
]


def _flag(rule: str, detail: str) -> dict[str, Any]:
    return {"rule": rule, "version": RULE_VERSION, "detail": detail}


def evaluate_legitimacy(
    job: Job,
    *,
    company_in_universe: bool,
    repost_count: int = 0,
    country_median_usd: int | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return legitimacy flags for a job row. Pure functions, <1ms/job."""
    today = today or date.today()
    flags: list[dict[str, Any]] = []
    text = f"{job.title or ''} {job.description or ''}"

    if job.posted_at and (today - job.posted_at).days > 60 and job.is_active:
        flags.append(_flag("stale_posting", f"posted {(today - job.posted_at).days} days ago"))

    if not company_in_universe:
        flags.append(_flag("no_company_record", "company absent from universe table"))

    for pattern, reason in _SCAM_PATTERNS:
        if pattern.search(text):
            flags.append(_flag("scam_pattern", reason))

    if (
        country_median_usd
        and job.salary_usd_max
        and job.salary_usd_max > country_median_usd * 3
    ):
        flags.append(
            _flag(
                "suspicious_salary",
                f"max salary >3× country median (${country_median_usd:,})",
            )
        )

    if repost_count >= 3:
        flags.append(_flag("reposted_3x", f"{repost_count} reposts in 90 days"))

    return flags


def is_warning_tone(flags: list[dict[str, Any]]) -> bool:
    """Two+ flags → warning tone; stale_posting alone is info."""
    if len(flags) >= 2:
        return True
    if len(flags) == 1 and flags[0]["rule"] != "stale_posting":
        return True
    return False
