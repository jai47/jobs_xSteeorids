"""Adzuna India official job search API source."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List
from urllib.parse import urlencode

from config import settings
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

ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"
REQUEST_DELAY_SECONDS = 0.75
RESULTS_PER_PAGE = 50
MAX_PAGES_PER_QUERY = 2
# Keep Adzuna max_days_old aligned with BaseSource.MAX_AGE_DAYS.
MAX_AGE_DAYS_SAFE = 30


class AdzunaSource(BaseSource):
    """Fetch AI/ML roles in India via Adzuna's official API.

    Skips entirely when ADZUNA_APP_ID / ADZUNA_APP_KEY are unset.
    """

    source_name = "adzuna"
    seed_filename = "adzuna_queries.txt"

    async def fetch(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> List[JobDict]:
        app_id = (settings.adzuna_app_id or "").strip()
        app_key = (settings.adzuna_app_key or "").strip()
        if not app_id or not app_key:
            log.info("Adzuna skipped — ADZUNA_APP_ID / ADZUNA_APP_KEY not configured")
            if progress_callback:
                progress_callback("adzuna: skipped (no API keys)")
            return []

        seeds = self.search_queries()
        jobs: list[JobDict] = []
        seen_ids: set[str] = set()
        total = len(seeds)
        async with get_async_client() as client:
            for index, query in enumerate(seeds, start=1):
                if progress_callback:
                    progress_callback(f"adzuna [{index}/{total}] {query}")
                try:
                    batch = await self._fetch_query(client, query, app_id, app_key)
                    for job in batch:
                        if job["external_id"] in seen_ids:
                            continue
                        seen_ids.add(job["external_id"])
                        jobs.append(job)
                except HTTPFetchError as exc:
                    log.warning("Adzuna fetch failed for %s: %s", query, exc)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return jobs

    async def _fetch_query(
        self,
        client,
        query: str,
        app_id: str,
        app_key: str,
    ) -> list[JobDict]:
        results: list[JobDict] = []
        for page in range(1, MAX_PAGES_PER_QUERY + 1):
            params = urlencode(
                {
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": query,
                    "results_per_page": RESULTS_PER_PAGE,
                    "max_days_old": MAX_AGE_DAYS_SAFE,
                    "content-type": "application/json",
                }
            )
            url = f"{ADZUNA_API.format(page=page)}?{params}"
            payload = await fetch_json(client, "GET", url)
            if not payload:
                break
            items = payload.get("results") or []
            if not items:
                break
            for item in items:
                job = self._map_item(item)
                if job is not None:
                    results.append(job)
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return results

    def _map_item(self, item: dict) -> JobDict | None:
        title = item.get("title") or ""
        if not self.is_target_role(title):
            return None

        location_obj = item.get("location") or {}
        location_name = location_obj.get("display_name") or ""
        company_obj = item.get("company") or {}
        company = company_obj.get("display_name") or "Unknown"
        description = strip_html(item.get("description") or "")
        posted_at = self.parse_posted_date(item.get("created"))
        if not self.is_recent_enough(posted_at):
            return None

        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        if salary_min and salary_max:
            salary_display = f"₹{int(salary_min)}–₹{int(salary_max)}"
        elif salary_min:
            salary_display = f"₹{int(salary_min)}+"
        else:
            salary_display = extract_salary_display(description) or None

        country, city = parse_country_and_city(location_name)
        if country is None:
            country = "IN"

        external_id = str(item.get("id") or "")
        if not external_id:
            return None

        return JobDict(
            source=self.source_name,
            external_id=external_id,
            url=item.get("redirect_url") or item.get("adref") or "",
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
