"""Registered job sources."""

from __future__ import annotations

import asyncio
import logging

from pipeline.sources.ashby import AshbySource
from pipeline.sources.base import BaseSource, JobDict
from pipeline.sources.greenhouse import GreenhouseSource
from pipeline.sources.lever import LeverSource

log = logging.getLogger(__name__)

SOURCES: list[type[BaseSource]] = [GreenhouseSource, LeverSource, AshbySource]


async def fetch_all_sources() -> list[JobDict]:
    """Fetch jobs from every registered source."""
    all_jobs: list[JobDict] = []
    for source_cls in SOURCES:
        source = source_cls()
        try:
            jobs = await source.fetch()
            log.info("%s returned %s jobs", source.source_name, len(jobs))
            all_jobs.extend(jobs)
        except Exception as exc:
            log.error("Source %s failed: %s", source.source_name, exc)
    return all_jobs


def fetch_all_sources_sync() -> list[JobDict]:
    """Synchronous wrapper for scripts and tests."""
    return asyncio.run(fetch_all_sources())
