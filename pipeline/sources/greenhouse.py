"""Greenhouse job board source."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List

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

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
REQUEST_DELAY_SECONDS = 1.0


class GreenhouseSource(BaseSource):
    """Fetch AI/ML roles from Greenhouse public boards."""

    source_name = "greenhouse"
    seed_filename = "greenhouse_boards.txt"

    async def fetch(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> List[JobDict]:
        seeds = self.load_seeds()
        jobs: list[JobDict] = []
        total = len(seeds)
        async with get_async_client() as client:
            for index, board in enumerate(seeds, start=1):
                if progress_callback:
                    progress_callback(f"greenhouse [{index}/{total}] {board}")
                try:
                    board_jobs = await self._fetch_board(client, board)
                    jobs.extend(board_jobs)
                except HTTPFetchError as exc:
                    log.warning("Greenhouse fetch failed for %s: %s", board, exc)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return jobs

    async def _fetch_board(self, client, board: str) -> list[JobDict]:
        url = f"{GREENHOUSE_API.format(board=board)}?content=true"
        payload = await fetch_json(client, "GET", url)
        if not payload:
            return []

        company = self.format_company_name(board)
        results: list[JobDict] = []

        for item in payload.get("jobs", []):
            title = item.get("title", "")
            if not self.is_target_role(title):
                continue

            location_name = (item.get("location") or {}).get("name")
            description_html = item.get("content") or ""
            description = strip_html(description_html)
            posted_at = self.parse_posted_date(item.get("updated_at"))
            if not self.is_recent_enough(posted_at):
                continue

            country, city = parse_country_and_city(location_name)
            salary_display = extract_salary_display(description)

            results.append(
                JobDict(
                    source=self.source_name,
                    external_id=str(item.get("id", "")),
                    url=item.get("absolute_url", ""),
                    company=company,
                    title=title,
                    country=country,
                    city=city,
                    remote_type=parse_remote_type(location_name),
                    salary_display=salary_display,
                    visa_keywords=extract_visa_keywords(description),
                    skills_required=extract_skills(description),
                    experience_min=extract_experience_min(description),
                    description=description,
                    posted_at=posted_at,
                )
            )
        return results
