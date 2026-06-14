"""Lever job board source."""

from __future__ import annotations

import asyncio
import logging
from typing import List

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

LEVER_API = "https://api.lever.co/v0/postings/{board}"
REQUEST_DELAY_SECONDS = 0.1


class LeverSource(BaseSource):
    """Fetch AI/ML roles from Lever public boards."""

    source_name = "lever"
    seed_filename = "lever_boards.txt"

    async def fetch(self) -> List[JobDict]:
        seeds = self.load_seeds()
        jobs: list[JobDict] = []
        async with get_async_client() as client:
            for board in seeds:
                try:
                    board_jobs = await self._fetch_board(client, board)
                    jobs.extend(board_jobs)
                except HTTPFetchError as exc:
                    log.warning("Lever fetch failed for %s: %s", board, exc)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return jobs

    async def _fetch_board(self, client, board: str) -> list[JobDict]:
        url = f"{LEVER_API.format(board=board)}?mode=json"
        payload = await fetch_json(client, "GET", url)
        if not payload:
            return []

        company = self.format_company_name(board)
        results: list[JobDict] = []

        for item in payload:
            title = item.get("text", "")
            if not self.is_target_role(title):
                continue

            categories = item.get("categories") or {}
            location_name = categories.get("location")
            description = item.get("descriptionPlain") or strip_html(item.get("description", ""))
            posted_at = self.parse_posted_date(item.get("createdAt"))
            if not self.is_recent_enough(posted_at):
                continue

            country, city = parse_country_and_city(location_name)
            salary_display = item.get("salaryRange") or extract_salary_display(description)

            results.append(
                JobDict(
                    source=self.source_name,
                    external_id=str(item.get("id", "")),
                    url=item.get("hostedUrl", ""),
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
