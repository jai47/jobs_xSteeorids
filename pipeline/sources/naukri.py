"""Naukri.com job search source (fail-soft on reCAPTCHA)."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, List
from urllib.parse import quote_plus, urlencode

import httpx

from core.http import HTTP_TIMEOUT, HTTPFetchError, get_async_client
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

NAUKRI_SEARCH_API = "https://www.naukri.com/jobapi/v3/search"
REQUEST_DELAY_SECONDS = 4.0
RESULTS_PER_PAGE = 20
MAX_PAGES_PER_QUERY = 2

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "AppId": "109",
    "SystemId": "Naukri",
}


class NaukriSource(BaseSource):
    """Fetch AI/ML roles from Naukri's internal search API.

    Naukri often returns HTTP 406 (reCAPTCHA required). That is treated as a
    soft failure: log a warning and return an empty list so the pipeline continues.
    """

    source_name = "naukri"
    seed_filename = "naukri_queries.txt"

    async def fetch(
        self,
        progress_callback: Callable[[str], None] | None = None,
    ) -> List[JobDict]:
        seeds = self.load_seeds()
        jobs: list[JobDict] = []
        seen_ids: set[str] = set()
        total = len(seeds)
        captcha_blocked = False

        async with get_async_client() as client:
            for index, seed in enumerate(seeds, start=1):
                keyword, location = self._parse_seed(seed)
                if progress_callback:
                    label = f"{keyword}" + (f" @ {location}" if location else "")
                    progress_callback(f"naukri [{index}/{total}] {label}")
                try:
                    batch, blocked = await self._fetch_query(client, keyword, location)
                    if blocked:
                        captcha_blocked = True
                        break
                    for job in batch:
                        if job["external_id"] in seen_ids:
                            continue
                        seen_ids.add(job["external_id"])
                        jobs.append(job)
                except HTTPFetchError as exc:
                    log.warning("Naukri fetch failed for %s: %s", seed, exc)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

        if captcha_blocked:
            log.warning(
                "Naukri blocked by reCAPTCHA — returning %s jobs collected before block",
                len(jobs),
            )
            if progress_callback:
                progress_callback("naukri: blocked by reCAPTCHA (fail-soft)")
        return jobs

    @staticmethod
    def _parse_seed(seed: str) -> tuple[str, str]:
        if "|" in seed:
            keyword, location = seed.split("|", 1)
            return keyword.strip(), location.strip()
        return seed.strip(), ""

    async def _fetch_query(
        self,
        client: httpx.AsyncClient,
        keyword: str,
        location: str,
    ) -> tuple[list[JobDict], bool]:
        """Return (jobs, captcha_blocked)."""
        results: list[JobDict] = []
        seo_key = keyword.lower().replace(" ", "-") + "-jobs"
        if location:
            seo_key = f"{seo_key}-in-{location.lower().replace(' ', '-')}"

        for page in range(1, MAX_PAGES_PER_QUERY + 1):
            params: dict[str, Any] = {
                "noOfResults": RESULTS_PER_PAGE,
                "urlType": "search_by_keyword",
                "searchType": "adv",
                "keyword": keyword,
                "pageNo": page,
                "k": keyword,
                "seoKey": seo_key,
                "src": "jobsearchDesk",
                "latLong": "",
            }
            if location:
                params["location"] = location
                params["l"] = location

            url = f"{NAUKRI_SEARCH_API}?{urlencode(params, quote_via=quote_plus)}"
            headers = {
                **_BROWSER_HEADERS,
                "Referer": f"https://www.naukri.com/{seo_key}",
            }
            payload, blocked = await self._get_json_failsoft(client, url, headers)
            if blocked:
                return results, True
            if not payload:
                break

            items = payload.get("jobDetails") or payload.get("jobs") or []
            if not items:
                break
            for item in items:
                job = self._map_item(item)
                if job is not None:
                    results.append(job)
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
        return results, False

    async def _get_json_failsoft(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
    ) -> tuple[Any | None, bool]:
        """Fetch JSON; treat 404/406 as soft empty. 406 marks captcha block."""
        try:
            response = await client.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        except httpx.HTTPError as exc:
            raise HTTPFetchError(f"Failed to fetch {url}") from exc

        if response.status_code in (404,):
            return None, False
        if response.status_code == 406:
            return None, True
        if response.status_code >= 400:
            body = response.text[:200]
            if "recaptcha" in body.lower():
                return None, True
            raise HTTPFetchError(f"HTTP {response.status_code} on {url}: {body}")

        try:
            data = response.json()
        except ValueError as exc:
            raise HTTPFetchError(f"Invalid JSON from {url}") from exc

        if isinstance(data, dict) and "recaptcha" in str(data.get("message", "")).lower():
            return None, True
        return data, False

    def _map_item(self, item: dict) -> JobDict | None:
        title = item.get("title") or item.get("jobTitle") or ""
        if not self.is_target_role(title):
            return None

        company = (
            item.get("companyName")
            or item.get("company")
            or (item.get("companyId") if isinstance(item.get("companyId"), str) else None)
            or "Unknown"
        )
        jd_path = item.get("jdURL") or item.get("jobUrl") or ""
        url = jd_path if jd_path.startswith("http") else f"https://www.naukri.com{jd_path}"

        placeholders = item.get("placeholders") or []
        location_name = ""
        salary_raw = ""
        experience_raw = ""
        for placeholder in placeholders:
            if not isinstance(placeholder, dict):
                continue
            label = (placeholder.get("type") or placeholder.get("label") or "").lower()
            value = placeholder.get("label") or placeholder.get("placeholderValue") or ""
            if "location" in label or placeholder.get("type") == "location":
                location_name = value or location_name
            elif "salary" in label or placeholder.get("type") == "salary":
                salary_raw = value or salary_raw
            elif "experience" in label or placeholder.get("type") == "experience":
                experience_raw = value or experience_raw

        location_name = (
            location_name
            or item.get("placeHolders")
            or item.get("footerPlaceholderLabel")
            or ""
        )
        if isinstance(location_name, list):
            location_name = ", ".join(str(x) for x in location_name)

        description = strip_html(
            item.get("jobDescription")
            or item.get("description")
            or item.get("jobDescriptionSnippet")
            or ""
        )
        tags = item.get("tagsAndSkills") or item.get("skills") or ""
        if isinstance(tags, str) and tags:
            description = f"{description}\nSkills: {tags}".strip()

        posted_at = self.parse_posted_date(
            item.get("createdDate") or item.get("postingDate") or item.get("createdDateTime")
        )
        if posted_at is None:
            posted_at = self._parse_relative_posted(item.get("footerPlaceholderLabel"))
        if not self.is_recent_enough(posted_at):
            return None

        country, city = parse_country_and_city(str(location_name))
        if country is None and location_name:
            country = "IN"

        salary_display = salary_raw or extract_salary_display(description) or None
        experience_min = extract_experience_min(experience_raw or description)
        skills = extract_skills(description)
        if isinstance(tags, str):
            for skill in tags.split(","):
                cleaned = skill.strip().lower()
                if cleaned and cleaned not in skills:
                    skills.append(cleaned)

        external_id = str(
            item.get("jobId") or item.get("jobIdEncrypted") or item.get("id") or ""
        )
        if not external_id:
            return None

        return JobDict(
            source=self.source_name,
            external_id=external_id,
            url=url,
            company=str(company),
            title=title,
            country=country,
            city=city,
            remote_type=parse_remote_type(str(location_name)),
            salary_display=salary_display,
            visa_keywords=extract_visa_keywords(description),
            skills_required=skills,
            experience_min=experience_min,
            description=description,
            posted_at=posted_at,
        )

    @staticmethod
    def _parse_relative_posted(value: Any):
        """Parse Naukri relative labels like '1 Day Ago' into a date when possible."""
        from datetime import date, timedelta

        if not isinstance(value, str):
            return None
        match = re.search(r"(\d+)\s*(day|days|hour|hours)\s*ago", value, re.IGNORECASE)
        if not match:
            if re.search(r"just now|today|few hours", value, re.IGNORECASE):
                return date.today()
            return None
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("hour"):
            return date.today()
        return date.today() - timedelta(days=amount)
