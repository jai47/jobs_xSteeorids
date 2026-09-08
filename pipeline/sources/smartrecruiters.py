"""SmartRecruiters public company postings API source."""

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

SMARTRECRUITERS_API = (
    "https://api.smartrecruiters.com/v1/companies/{company}/postings"
)
REQUEST_DELAY_SECONDS = 0.5
RESULTS_LIMIT = 100


class SmartRecruitersSource(BaseSource):
    """Fetch roles from SmartRecruiters public company postings."""

    source_name = "smartrecruiters"
    seed_filename = "smartrecruiters_companies.txt"

    async def fetch(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> List[JobDict]:
        seeds = self.load_seeds()
        jobs: list[JobDict] = []
        total = len(seeds)
        async with get_async_client() as client:
            for index, company in enumerate(seeds, start=1):
                if progress_callback:
                    progress_callback(f"smartrecruiters [{index}/{total}] {company}")
                try:
                    jobs.extend(await self._fetch_company(client, company))
                except HTTPFetchError as exc:
                    log.warning("SmartRecruiters fetch failed for %s: %s", company, exc)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return jobs

    async def _fetch_company(self, client, company: str) -> list[JobDict]:
        url = f"{SMARTRECRUITERS_API.format(company=company)}?limit={RESULTS_LIMIT}"
        payload = await fetch_json(client, "GET", url)
        if not payload:
            return []

        display_company = self.format_company_name(company)
        results: list[JobDict] = []
        for item in payload.get("content") or []:
            title = item.get("name") or item.get("title") or ""
            if not self.is_target_role(title):
                continue

            location = item.get("location") or {}
            location_name = ", ".join(
                part
                for part in [
                    location.get("city"),
                    location.get("region"),
                    location.get("country"),
                ]
                if part
            ) or "Remote"
            description = title
            job_ad = item.get("jobAd")
            if isinstance(job_ad, dict):
                sections = job_ad.get("sections") or {}
                if isinstance(sections, dict):
                    jd = sections.get("jobDescription") or {}
                    if isinstance(jd, dict) and jd.get("text"):
                        description = strip_html(str(jd["text"]))
            posted_at = self.parse_posted_date(
                item.get("releasedDate") or item.get("createdOn") or item.get("updatedOn")
            )
            if not self.is_recent_enough(posted_at):
                continue

            external_id = str(item.get("id") or item.get("uuid") or "")
            if not external_id:
                continue
            apply_url = (
                item.get("applyUrl")
                or item.get("ref")
                or f"https://jobs.smartrecruiters.com/{company}/{external_id}"
            )
            country, city = parse_country_and_city(location_name)
            results.append(
                JobDict(
                    source=self.source_name,
                    external_id=external_id,
                    url=apply_url,
                    company=display_company,
                    title=title,
                    country=country,
                    city=city,
                    remote_type=parse_remote_type(location_name),
                    salary_display=extract_salary_display(description),
                    visa_keywords=extract_visa_keywords(description),
                    skills_required=extract_skills(description),
                    experience_min=extract_experience_min(description),
                    description=description,
                    posted_at=posted_at,
                )
            )
        return results
