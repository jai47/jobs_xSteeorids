"""Remotive remote jobs public API source."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List
from urllib.parse import quote_plus

from core.http import HTTPFetchError, fetch_json, get_async_client
from core.text import (
    extract_experience_min,
    extract_salary_display,
    extract_skills,
    extract_visa_keywords,
    parse_country_and_city,
    parse_remote_type,
    strip_html,
)
from pipeline.sources.base import BaseSource, JobDict

log = logging.getLogger(__name__)

REMOTIVE_API = "https://remotive.com/api/remote-jobs"
REQUEST_DELAY_SECONDS = 0.5
RESULT_LIMIT = 100


class RemotiveSource(BaseSource):
    """Fetch AI/ML roles from Remotive's public remote-jobs API."""

    source_name = "remotive"
    seed_filename = "remotive_queries.txt"

    async def fetch(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> List[JobDict]:
        seeds = self.load_seeds()
        jobs: list[JobDict] = []
        seen_ids: set[str] = set()
        total = len(seeds)
        async with get_async_client() as client:
            for index, query in enumerate(seeds, start=1):
                if progress_callback:
                    progress_callback(f"remotive [{index}/{total}] {query}")
                try:
                    batch = await self._fetch_query(client, query)
                    for job in batch:
                        if job["external_id"] in seen_ids:
                            continue
                        seen_ids.add(job["external_id"])
                        jobs.append(job)
                except HTTPFetchError as exc:
                    log.warning("Remotive fetch failed for %s: %s", query, exc)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return jobs

    async def _fetch_query(self, client, query: str) -> list[JobDict]:
        url = f"{REMOTIVE_API}?search={quote_plus(query)}&limit={RESULT_LIMIT}"
        payload = await fetch_json(client, "GET", url)
        if not payload:
            return []

        results: list[JobDict] = []
        for item in payload.get("jobs") or []:
            title = item.get("title") or ""
            if not self.is_target_role(title):
                continue

            location_name = item.get("candidate_required_location") or "Remote"
            description = strip_html(item.get("description") or "")
            posted_at = self.parse_posted_date(item.get("publication_date"))
            if not self.is_recent_enough(posted_at):
                continue

            tags = item.get("tags") or []
            skills = extract_skills(description)
            for tag in tags:
                cleaned = str(tag).strip().lower()
                if cleaned and cleaned not in skills:
                    skills.append(cleaned)

            country, city = parse_country_and_city(location_name)
            salary_display = item.get("salary") or extract_salary_display(description)

            results.append(
                JobDict(
                    source=self.source_name,
                    external_id=str(item.get("id", "")),
                    url=item.get("url") or "",
                    company=item.get("company_name") or "Unknown",
                    title=title,
                    country=country,
                    city=city,
                    remote_type=parse_remote_type(location_name) or "remote",
                    salary_display=salary_display or None,
                    visa_keywords=extract_visa_keywords(description),
                    skills_required=skills,
                    experience_min=extract_experience_min(description),
                    description=description,
                    posted_at=posted_at,
                )
            )
        return results
