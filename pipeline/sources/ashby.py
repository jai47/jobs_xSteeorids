"""Ashby job board source."""

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

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{org}"
REQUEST_DELAY_SECONDS = 0.5


class AshbySource(BaseSource):
    """Fetch AI/ML roles from Ashby public job boards."""

    source_name = "ashby"
    seed_filename = "ashby_orgs.txt"

    async def fetch(self) -> List[JobDict]:
        seeds = self.load_seeds()
        jobs: list[JobDict] = []
        async with get_async_client() as client:
            for org in seeds:
                try:
                    org_jobs = await self._fetch_org(client, org)
                    jobs.extend(org_jobs)
                except HTTPFetchError as exc:
                    log.warning("Ashby fetch failed for %s: %s", org, exc)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return jobs

    async def _fetch_org(self, client, org: str) -> list[JobDict]:
        url = f"{ASHBY_API.format(org=org)}?includeCompensation=true"
        payload = await fetch_json(client, "GET", url)
        if not payload:
            return []

        company = self.format_company_name(org)
        results: list[JobDict] = []

        for item in payload.get("jobs", []):
            title = item.get("title", "")
            if not self.is_target_role(title):
                continue

            location_name = item.get("location")
            if isinstance(location_name, dict):
                location_name = location_name.get("name") or location_name.get("locationName")

            description = (
                item.get("descriptionPlain")
                or strip_html(item.get("descriptionHtml", ""))
                or strip_html(item.get("description", ""))
            )
            posted_at = self.parse_posted_date(
                item.get("publishedAt") or item.get("updatedAt")
            )
            if not self.is_recent_enough(posted_at):
                continue

            country, city = parse_country_and_city(location_name)
            compensation = item.get("compensation") or {}
            salary_display = (
                compensation.get("scrapeableCompensationSalarySummary")
                or compensation.get("compensationTierSummary")
                or extract_salary_display(description)
            )

            workplace = item.get("workplaceType") or item.get("employmentType")
            remote_type = parse_remote_type(workplace or location_name)

            results.append(
                JobDict(
                    source=self.source_name,
                    external_id=str(item.get("id", "")),
                    url=item.get("jobUrl", ""),
                    company=company,
                    title=title,
                    country=country,
                    city=city,
                    remote_type=remote_type,
                    salary_display=salary_display,
                    visa_keywords=extract_visa_keywords(description),
                    skills_required=extract_skills(description),
                    experience_min=extract_experience_min(description),
                    description=description,
                    posted_at=posted_at,
                )
            )
        return results
