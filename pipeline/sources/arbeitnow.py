"""Arbeitnow public job-board API source."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List
from urllib.parse import urlencode

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

ARBEITNOW_API = "https://www.arbeitnow.com/api/job-board-api"
REQUEST_DELAY_SECONDS = 0.5
MAX_PAGES = 3


class ArbeitnowSource(BaseSource):
    """Fetch AI/ML roles from Arbeitnow's public job-board API."""

    source_name = "arbeitnow"
    seed_filename = "arbeitnow_feed.txt"

    async def fetch(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> List[JobDict]:
        jobs: list[JobDict] = []
        seen_ids: set[str] = set()
        async with get_async_client() as client:
            for page in range(1, MAX_PAGES + 1):
                if progress_callback:
                    progress_callback(f"arbeitnow page {page}/{MAX_PAGES}")
                try:
                    batch = await self._fetch_page(client, page)
                except HTTPFetchError as exc:
                    log.warning("Arbeitnow fetch failed on page %s: %s", page, exc)
                    break
                if not batch:
                    break
                for job in batch:
                    if job["external_id"] in seen_ids:
                        continue
                    seen_ids.add(job["external_id"])
                    jobs.append(job)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return jobs

    async def _fetch_page(self, client, page: int) -> list[JobDict]:
        url = f"{ARBEITNOW_API}?{urlencode({'page': page})}"
        payload = await fetch_json(client, "GET", url)
        if not payload:
            return []

        results: list[JobDict] = []
        for item in payload.get("data") or []:
            title = item.get("title") or ""
            if not self.is_target_role(title):
                continue

            location_name = item.get("location") or ""
            description = strip_html(item.get("description") or "")
            posted_at = self.parse_posted_date(item.get("created_at"))
            if not self.is_recent_enough(posted_at):
                continue

            tags = [str(t).lower() for t in (item.get("tags") or [])]
            skills = extract_skills(description)
            for tag in tags:
                if tag and tag not in skills:
                    skills.append(tag)

            country, city = parse_country_and_city(location_name)
            remote_type = "remote" if item.get("remote") else parse_remote_type(location_name)
            external_id = str(item.get("slug") or "")
            if not external_id:
                continue

            results.append(
                JobDict(
                    source=self.source_name,
                    external_id=external_id,
                    url=item.get("url") or "",
                    company=item.get("company_name") or "Unknown",
                    title=title,
                    country=country,
                    city=city,
                    remote_type=remote_type,
                    salary_display=extract_salary_display(description) or None,
                    visa_keywords=extract_visa_keywords(description),
                    skills_required=skills,
                    experience_min=extract_experience_min(description),
                    description=description,
                    posted_at=posted_at,
                )
            )
        return results
