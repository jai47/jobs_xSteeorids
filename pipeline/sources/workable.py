"""Workable public widget API source."""

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

WORKABLE_API = "https://apply.workable.com/api/v1/widget/accounts/{account}"
REQUEST_DELAY_SECONDS = 0.5


class WorkableSource(BaseSource):
    """Fetch roles from Workable public career widgets."""

    source_name = "workable"
    seed_filename = "workable_accounts.txt"

    async def fetch(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> List[JobDict]:
        seeds = self.load_seeds()
        jobs: list[JobDict] = []
        total = len(seeds)
        async with get_async_client() as client:
            for index, account in enumerate(seeds, start=1):
                if progress_callback:
                    progress_callback(f"workable [{index}/{total}] {account}")
                try:
                    jobs.extend(await self._fetch_account(client, account))
                except HTTPFetchError as exc:
                    log.warning("Workable fetch failed for %s: %s", account, exc)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return jobs

    async def _fetch_account(self, client, account: str) -> list[JobDict]:
        url = WORKABLE_API.format(account=account)
        payload = await fetch_json(client, "GET", url)
        if not payload:
            return []

        company = (
            payload.get("name")
            or self.format_company_name(account)
        )
        results: list[JobDict] = []
        for item in payload.get("jobs") or []:
            title = item.get("title") or ""
            if not self.is_target_role(title):
                continue

            location_name = item.get("location") or item.get("city") or ""
            if isinstance(location_name, dict):
                location_name = (
                    location_name.get("city")
                    or location_name.get("country")
                    or location_name.get("location_str")
                    or ""
                )
            remote = bool(item.get("remote"))
            location_label = "Remote" if remote and not location_name else str(location_name)

            description = strip_html(
                item.get("description")
                or item.get("full_description")
                or item.get("application_url")
                or title
            )
            posted_at = self.parse_posted_date(
                item.get("published_on") or item.get("created_at") or item.get("updated_at")
            )
            if not self.is_recent_enough(posted_at):
                continue

            shortcode = str(item.get("shortcode") or item.get("id") or "")
            if not shortcode:
                continue
            apply_url = (
                item.get("url")
                or item.get("application_url")
                or f"https://apply.workable.com/{account}/j/{shortcode}/"
            )
            country, city = parse_country_and_city(location_label)
            results.append(
                JobDict(
                    source=self.source_name,
                    external_id=shortcode,
                    url=apply_url,
                    company=str(company),
                    title=title,
                    country=country,
                    city=city,
                    remote_type="remote" if remote else parse_remote_type(location_label),
                    salary_display=extract_salary_display(description),
                    visa_keywords=extract_visa_keywords(description),
                    skills_required=extract_skills(description),
                    experience_min=extract_experience_min(description),
                    description=description,
                    posted_at=posted_at,
                )
            )
        return results
