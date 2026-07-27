"""RemoteOK public jobs API source."""

from __future__ import annotations

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

REMOTEOK_API = "https://remoteok.com/api"
USER_AGENT = "AI-Career-Copilot/1.0 (personal job discovery)"


class RemoteOKSource(BaseSource):
    """Fetch AI/ML roles from RemoteOK's public feed."""

    source_name = "remoteok"
    seed_filename = "remoteok_feed.txt"

    async def fetch(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> List[JobDict]:
        if progress_callback:
            progress_callback("remoteok fetching public feed...")
        async with get_async_client() as client:
            try:
                payload = await fetch_json(
                    client,
                    "GET",
                    REMOTEOK_API,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
            except HTTPFetchError as exc:
                log.warning("RemoteOK fetch failed: %s", exc)
                return []

        if not isinstance(payload, list) or len(payload) < 2:
            return []

        results: list[JobDict] = []
        # First element is a legal notice / metadata object.
        for item in payload[1:]:
            if not isinstance(item, dict):
                continue
            title = item.get("position") or item.get("title") or ""
            if not self.is_target_role(title):
                continue
            tags = [str(t).lower() for t in (item.get("tags") or [])]

            location_name = item.get("location") or "Remote"
            description = strip_html(item.get("description") or "")
            posted_at = self.parse_posted_date(item.get("date"))
            if posted_at is None and item.get("epoch") is not None:
                posted_at = self.parse_posted_date(float(item["epoch"]) * 1000)
            if not self.is_recent_enough(posted_at):
                continue

            salary_min = item.get("salary_min")
            salary_max = item.get("salary_max")
            if salary_min and salary_max:
                salary_display = f"${salary_min}–${salary_max}"
            else:
                salary_display = extract_salary_display(description)

            country, city = parse_country_and_city(location_name)
            external_id = str(item.get("id") or item.get("slug") or "")
            if not external_id:
                continue

            skills = extract_skills(description)
            for tag in tags:
                if tag and tag not in skills:
                    skills.append(tag)

            results.append(
                JobDict(
                    source=self.source_name,
                    external_id=external_id,
                    url=item.get("url") or item.get("apply_url") or "",
                    company=item.get("company") or "Unknown",
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
