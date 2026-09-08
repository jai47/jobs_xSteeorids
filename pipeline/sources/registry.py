"""Registered job sources."""

from __future__ import annotations

import asyncio
import logging

from typing import Callable

from pipeline.sources.adzuna import AdzunaSource
from pipeline.sources.arbeitnow import ArbeitnowSource
from pipeline.sources.ashby import AshbySource
from pipeline.sources.base import BaseSource, JobDict
from pipeline.sources.greenhouse import GreenhouseSource
from pipeline.sources.lever import LeverSource
from pipeline.sources.naukri import NaukriSource
from pipeline.sources.remoteok import RemoteOKSource
from pipeline.sources.remotive import RemotiveSource
from pipeline.role_targets import RoleProfile

log = logging.getLogger(__name__)

SOURCES: list[type[BaseSource]] = [
    GreenhouseSource,
    LeverSource,
    AshbySource,
    RemotiveSource,
    RemoteOKSource,
    ArbeitnowSource,
    AdzunaSource,
    NaukriSource,
]


async def fetch_all_sources(
    progress_callback: Callable[[str], None] | None = None,
    role_profile: RoleProfile | None = None,
) -> list[JobDict]:
    """Fetch jobs from every registered source, targeting the user's roles."""
    all_jobs: list[JobDict] = []
    for source_cls in SOURCES:
        source = source_cls(role_profile=role_profile)
        if progress_callback:
            progress_callback(f"Fetching {source.source_name} boards...")
        try:
            jobs = await source.fetch(progress_callback=progress_callback)
            log.info("%s returned %s jobs", source.source_name, len(jobs))
            if progress_callback:
                progress_callback(f"{source.source_name}: {len(jobs)} jobs fetched")
            all_jobs.extend(jobs)
        except Exception as exc:
            log.error("Source %s failed: %s", source.source_name, exc)
            if progress_callback:
                progress_callback(f"{source.source_name}: failed — {exc}")
    return all_jobs


def fetch_all_sources_sync(
    progress_callback: Callable[[str], None] | None = None,
    role_profile: RoleProfile | None = None,
) -> list[JobDict]:
    """Synchronous wrapper for scripts and tests."""
    return asyncio.run(
        fetch_all_sources(progress_callback=progress_callback, role_profile=role_profile)
    )
