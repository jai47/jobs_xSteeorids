"""
Abstract base for all job sources.
Adding a new source = subclass BaseSource + register in SOURCES list.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, TypedDict

from pipeline.role_targets import RoleProfile

log = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).resolve().parent / "seeds"
MAX_AGE_DAYS = 30


class JobDict(TypedDict):
    source: str
    external_id: str
    url: str
    company: str
    title: str
    country: Optional[str]
    city: Optional[str]
    remote_type: Optional[str]
    salary_display: Optional[str]
    visa_keywords: list[str]
    skills_required: list[str]
    experience_min: Optional[int]
    description: str
    posted_at: Optional[date]


class BaseSource(ABC):
    """
    Each source implements fetch().
    Returns a list of JobDicts matching the unified schema.
    Must handle its own rate limiting, retries, and error handling.
    Must discard postings older than 30 days.
    Must discard roles outside the run's target roles.
    """

    source_name: str
    seed_filename: str

    # Used only when a run supplies no RoleProfile (scripts, tests, ad-hoc fetches).
    TARGET_ROLES = [
        "ai engineer",
        "machine learning engineer",
        "ml engineer",
        "applied ai engineer",
        "data scientist",
        "senior data scientist",
        "computer vision engineer",
        "llm engineer",
        "generative ai engineer",
        "ai platform engineer",
    ]

    def __init__(self, role_profile: RoleProfile | None = None) -> None:
        self.role_profile = role_profile

    def load_seeds(self) -> list[str]:
        """Read company identifiers from the source seed file."""
        seed_path = SEEDS_DIR / self.seed_filename
        if not seed_path.is_file():
            log.warning("Seed file missing: %s", seed_path)
            return []

        seeds: list[str] = []
        for line in seed_path.read_text(encoding="utf-8").splitlines():
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            seeds.append(cleaned)
        return seeds

    def is_target_role(self, title: str) -> bool:
        """Return whether a job title falls inside the run's target roles."""
        if self.role_profile is not None:
            return self.role_profile.matches_title(title)
        lowered = title.lower()
        return any(role in lowered for role in self.TARGET_ROLES)

    def search_queries(self) -> list[str]:
        """Keyword queries for search-based sources, driven by the user's roles."""
        if self.role_profile is not None and self.role_profile.search_queries:
            return list(self.role_profile.search_queries)
        return self.load_seeds()

    def is_recent_enough(self, posted_at: date | None) -> bool:
        """Discard postings older than MAX_AGE_DAYS."""
        if posted_at is None:
            return True
        cutoff = date.today() - timedelta(days=MAX_AGE_DAYS)
        return posted_at >= cutoff

    @staticmethod
    def format_company_name(slug: str) -> str:
        """Convert a board slug into a display company name."""
        return slug.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def parse_posted_date(value: str | int | float | None) -> date | None:
        """Parse common ATS date formats into a date."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
        if isinstance(value, str):
            cleaned = value.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(cleaned).date()
            except ValueError:
                for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        return datetime.strptime(value[:19], fmt).date()
                    except ValueError:
                        continue
        return None

    @abstractmethod
    async def fetch(self) -> List[JobDict]:
        raise NotImplementedError
