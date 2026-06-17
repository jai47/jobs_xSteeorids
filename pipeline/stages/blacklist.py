"""
Removes jobs matching user blacklists before scoring.
Three blacklist types: company, role, location.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from pipeline.sources.base import JobDict


def apply_blacklist(jobs: list[JobDict], user) -> list[JobDict]:
    """Filter jobs that match any of the user's company, location, or role blacklists."""
    company_blocklist = {c.lower() for c in (user.blacklisted_companies or [])}
    location_blocklist = {loc.upper() for loc in (user.blacklisted_locations or [])}
    role_blocklist = user.blacklisted_roles or []

    filtered: list[JobDict] = []
    for job in jobs:
        if job["company"].lower() in company_blocklist:
            continue

        country = job.get("country")
        if country and country.upper() in location_blocklist:
            continue

        title = job.get("title", "")
        role_blocked = any(
            fuzz.token_sort_ratio(title.lower(), blocked_role.lower()) >= 85
            for blocked_role in role_blocklist
        )
        if role_blocked:
            continue

        filtered.append(job)

    return filtered
