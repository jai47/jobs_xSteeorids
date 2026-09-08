"""Role targeting derived from a user's stated preferences and resume.

Discovery used to hardcode an AI/ML title list, so every user received the same
AI/ML job universe no matter what their resume said. Sources now filter titles
and build keyword searches from the role families implied by the user profile.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

log = logging.getLogger(__name__)

MAX_SEARCH_QUERIES = 8

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise_title(text: str) -> str:
    """Lowercase and collapse punctuation so 'Full-Stack Dev.' -> 'full stack dev'."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


@dataclass(frozen=True)
class RoleFamily:
    """A group of interchangeable job titles the user could reasonably target."""

    key: str
    label: str
    # Whole-word phrases that identify a title as belonging to this family.
    title_keywords: tuple[str, ...]
    # Queries handed to keyword-search sources (Remotive, Adzuna, Naukri).
    search_queries: tuple[str, ...]
    # Resume skills that imply this family when no usable title exists.
    skill_hints: tuple[str, ...] = ()
    # Adjacent families a candidate for this family would also apply to.
    related: tuple[str, ...] = ()


# Ordered most-specific first: primary_family_for() returns the first match, so
# "Machine Learning Software Engineer" resolves to ai_ml rather than fullstack.
ROLE_FAMILIES: tuple[RoleFamily, ...] = (
    RoleFamily(
        key="ai_ml",
        label="AI / ML engineering",
        title_keywords=(
            "ai engineer",
            "ai ml",
            "ai platform engineer",
            "ai scientist",
            "applied ai",
            "applied ml",
            "applied scientist",
            "artificial intelligence",
            "computer vision",
            "cv engineer",
            "deep learning",
            "generative ai",
            "genai",
            "llm",
            "machine learning",
            "ml engineer",
            "ml infrastructure",
            "ml platform",
            "mlops",
            "nlp",
            "prompt engineer",
            "research engineer",
        ),
        search_queries=(
            "machine learning engineer",
            "ai engineer",
            "llm engineer",
            "computer vision engineer",
            "generative ai",
        ),
        skill_hints=(
            "pytorch",
            "tensorflow",
            "llm",
            "hugging face",
            "transformers",
            "computer vision",
            "nlp",
            "mlops",
            "rag",
            "langchain",
        ),
        related=("data_science",),
    ),
    RoleFamily(
        key="data_science",
        label="Data science",
        title_keywords=(
            "data scientist",
            "data science",
            "decision scientist",
            "quantitative analyst",
            "quantitative researcher",
            "research scientist",
            "statistician",
        ),
        search_queries=("data scientist", "data science", "applied scientist"),
        skill_hints=("pandas", "scikit learn", "statistics", "a/b testing", "numpy"),
        related=("ai_ml", "data_analytics"),
    ),
    RoleFamily(
        key="data_engineering",
        label="Data engineering",
        title_keywords=(
            "analytics engineer",
            "big data engineer",
            "data engineer",
            "data platform engineer",
            "data warehouse engineer",
            "etl developer",
            "etl engineer",
        ),
        search_queries=("data engineer", "analytics engineer", "big data engineer"),
        skill_hints=("spark", "airflow", "dbt", "snowflake", "hadoop", "kafka"),
        related=("data_analytics",),
    ),
    RoleFamily(
        key="data_analytics",
        label="Data / business analytics",
        title_keywords=(
            "bi analyst",
            "bi developer",
            "business analyst",
            "business intelligence",
            "data analyst",
            "product analyst",
            "reporting analyst",
        ),
        search_queries=("data analyst", "business intelligence analyst"),
        skill_hints=("tableau", "power bi", "looker"),
        related=("data_engineering",),
    ),
    RoleFamily(
        key="devops",
        label="DevOps / platform / SRE",
        title_keywords=(
            "build engineer",
            "cloud architect",
            "cloud engineer",
            "devops",
            "infrastructure engineer",
            "kubernetes engineer",
            "platform engineer",
            "release engineer",
            "site reliability engineer",
            "sre",
            "systems engineer",
        ),
        search_queries=("devops engineer", "site reliability engineer", "cloud engineer"),
        skill_hints=("kubernetes", "terraform", "ansible", "jenkins", "aws", "docker"),
        related=("backend",),
    ),
    RoleFamily(
        key="mobile",
        label="Mobile engineering",
        title_keywords=(
            "android developer",
            "android engineer",
            "flutter developer",
            "ios developer",
            "ios engineer",
            "kotlin developer",
            "mobile developer",
            "mobile engineer",
            "react native developer",
            "swift developer",
        ),
        search_queries=("mobile app developer", "android developer", "ios developer"),
        skill_hints=("flutter", "react native", "swift", "kotlin"),
        related=("fullstack",),
    ),
    RoleFamily(
        key="qa",
        label="QA / test automation",
        title_keywords=(
            "automation tester",
            "qa analyst",
            "qa engineer",
            "quality assurance",
            "sdet",
            "test automation engineer",
            "test engineer",
        ),
        search_queries=("qa engineer", "sdet", "test automation engineer"),
        skill_hints=("selenium", "cypress", "playwright", "testng"),
    ),
    RoleFamily(
        key="security",
        label="Security engineering",
        title_keywords=(
            "appsec",
            "application security",
            "cyber security",
            "cybersecurity",
            "information security",
            "penetration tester",
            "security analyst",
            "security engineer",
            "soc analyst",
        ),
        search_queries=("security engineer", "cyber security analyst"),
        skill_hints=("owasp", "penetration testing", "siem", "burp suite"),
    ),
    RoleFamily(
        key="embedded",
        label="Embedded / firmware",
        title_keywords=(
            "embedded developer",
            "embedded engineer",
            "embedded software engineer",
            "firmware engineer",
            "iot engineer",
        ),
        search_queries=("embedded software engineer", "firmware engineer"),
        skill_hints=("rtos", "microcontroller", "verilog"),
    ),
    RoleFamily(
        key="product",
        label="Product management",
        title_keywords=(
            "product manager",
            "product owner",
            "program manager",
            "technical product manager",
            "technical program manager",
        ),
        search_queries=("product manager", "technical program manager"),
    ),
    RoleFamily(
        key="design",
        label="Product design",
        title_keywords=(
            "interaction designer",
            "product designer",
            "ui designer",
            "ux designer",
            "ux researcher",
            "visual designer",
        ),
        search_queries=("product designer", "ux designer"),
        skill_hints=("figma", "sketch"),
    ),
    RoleFamily(
        key="frontend",
        label="Frontend engineering",
        title_keywords=(
            "angular developer",
            "frontend",
            "front end",
            "javascript developer",
            "react developer",
            "ui developer",
            "ui engineer",
            "vue developer",
        ),
        search_queries=("frontend developer", "frontend engineer", "react developer"),
        skill_hints=("react", "angular", "vue", "tailwind", "redux"),
        related=("fullstack",),
    ),
    RoleFamily(
        key="backend",
        label="Backend engineering",
        title_keywords=(
            "api developer",
            "api engineer",
            "back end",
            "backend",
            "dotnet developer",
            "go developer",
            "golang developer",
            "java developer",
            "microservices engineer",
            "net developer",
            "node developer",
            "node js developer",
            "php developer",
            "python developer",
            "ruby developer",
            "server side engineer",
        ),
        search_queries=(
            "backend developer",
            "backend engineer",
            "java developer",
            "python developer",
        ),
        skill_hints=("django", "flask", "fastapi", "spring boot", "express", "microservices"),
        related=("fullstack",),
    ),
    # Generic software titles rank last so specialised families win precedence.
    RoleFamily(
        key="fullstack",
        label="Full stack / software engineering",
        title_keywords=(
            "application developer",
            "applications engineer",
            "full stack",
            "fullstack",
            "mean stack",
            "mern",
            "mern stack",
            "member of technical staff",
            "product engineer",
            "sde",
            "software developer",
            "software development engineer",
            "software engineer",
            "web developer",
            "web engineer",
        ),
        search_queries=(
            "full stack developer",
            "full stack engineer",
            "software engineer",
            "mern stack developer",
            "web developer",
        ),
        skill_hints=("react", "node js", "express", "next js", "django", "spring boot"),
        related=("backend", "frontend"),
    ),
)

FAMILIES_BY_KEY: dict[str, RoleFamily] = {family.key: family for family in ROLE_FAMILIES}

# Preserved so a user with no usable resume signal still gets the original behaviour.
DEFAULT_FAMILIES: tuple[str, ...] = ("ai_ml", "data_science")


def _contains_phrase(normalised_text: str, phrase: str) -> bool:
    """Whole-word containment so 'ml engineer' does not match 'html engineer'."""
    return f" {phrase} " in f" {normalised_text} "


def families_for_text(text: str) -> set[str]:
    """Return every role family whose keywords appear in the text."""
    normalised = normalise_title(text)
    if not normalised:
        return set()
    return {
        family.key
        for family in ROLE_FAMILIES
        if any(_contains_phrase(normalised, keyword) for keyword in family.title_keywords)
    }


def primary_family_for(text: str) -> str | None:
    """Return the most specific family matching the text, or None when unknown."""
    normalised = normalise_title(text)
    if not normalised:
        return None
    for family in ROLE_FAMILIES:
        if any(_contains_phrase(normalised, keyword) for keyword in family.title_keywords):
            return family.key
    return None


def families_for_skills(skills: Iterable[str]) -> set[str]:
    """Infer families from resume skills when no title signal is available."""
    normalised = {normalise_title(skill) for skill in skills if str(skill).strip()}
    if not normalised:
        return set()

    hits: dict[str, int] = {}
    for family in ROLE_FAMILIES:
        matched = sum(
            1
            for hint in family.skill_hints
            if any(_contains_phrase(skill, normalise_title(hint)) for skill in normalised)
        )
        if matched:
            hits[family.key] = matched

    if not hits:
        return set()
    best = max(hits.values())
    # Only keep families with real support; a single generic hint is not enough
    # to override everything else.
    return {key for key, count in hits.items() if count == best}


@dataclass(frozen=True)
class RoleProfile:
    """The role universe a single user's discovery and scoring should target."""

    families: tuple[str, ...]
    raw_keywords: tuple[str, ...]
    search_queries: tuple[str, ...]
    origin: str

    def matches_title(self, title: str) -> bool:
        """Return whether a job title is inside this user's target role universe."""
        if not self.families and not self.raw_keywords:
            return True
        normalised = normalise_title(title)
        if not normalised:
            return False
        if any(_contains_phrase(normalised, keyword) for keyword in self.raw_keywords):
            return True
        family = primary_family_for(normalised)
        if family is not None and family in self.families:
            return True
        # Non-catalog roles (nurse, teacher, accountant, …): keep titles that
        # share a distinctive token with the user's stated preferences.
        if self.raw_keywords and title_matches_custom_roles(normalised, self.raw_keywords):
            return True
        return False

    def describe(self) -> str:
        labels = [FAMILIES_BY_KEY[key].label for key in self.families if key in FAMILIES_BY_KEY]
        if labels:
            return ", ".join(labels)
        if self.raw_keywords:
            return ", ".join(self.raw_keywords[:4])
        return "any role"


def _expand_related(families: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    for key in families:
        if key not in expanded:
            expanded.append(key)
    for key in list(expanded):
        for related in FAMILIES_BY_KEY[key].related:
            if related not in expanded:
                expanded.append(related)
    return expanded


# Seniority and level markers narrow a keyword search far more than they help.
_QUERY_NOISE = frozenset(
    {
        "assistant",
        "associate",
        "chief",
        "head",
        "i",
        "ii",
        "iii",
        "intern",
        "internship",
        "iv",
        "j",
        "jr",
        "junior",
        "lead",
        "principal",
        "senior",
        "sr",
        "staff",
        "trainee",
    }
)


def _strip_seniority(role: str) -> str:
    tokens = [token for token in normalise_title(role).split() if token not in _QUERY_NOISE]
    return " ".join(tokens)


def _build_search_queries(raw_roles: Sequence[str], families: Sequence[str]) -> tuple[str, ...]:
    queries: list[str] = []

    def add(candidate: str) -> None:
        cleaned = normalise_title(candidate)
        if cleaned and cleaned not in queries:
            queries.append(cleaned)

    # The user's own wording is the most accurate query we have.
    for role in raw_roles:
        add(_strip_seniority(role))
    for key in families:
        for query in FAMILIES_BY_KEY[key].search_queries:
            add(query)
    return tuple(queries[:MAX_SEARCH_QUERIES])


# Words that appear in almost every professional title — never use them alone
# to decide that a custom (non-IT) role matches.
_GENERIC_ROLE_WORDS = frozenset(
    {
        "administrator",
        "analyst",
        "assistant",
        "associate",
        "chief",
        "consultant",
        "coordinator",
        "director",
        "executive",
        "head",
        "lead",
        "manager",
        "officer",
        "professional",
        "specialist",
        "supervisor",
    }
)


def distinctive_tokens(text: str) -> set[str]:
    """Tokens that can identify a custom role without matching every job title."""
    return {
        token
        for token in normalise_title(text).split()
        if len(token) >= 5
        and token not in _QUERY_NOISE
        and token not in _GENERIC_ROLE_WORDS
    }


def title_matches_custom_roles(title: str, raw_keywords: Sequence[str]) -> bool:
    """True when a non-catalog title shares a distinctive token with user roles."""
    title_tokens = distinctive_tokens(title)
    if not title_tokens:
        return False
    for keyword in raw_keywords:
        if title_tokens & distinctive_tokens(keyword):
            return True
    return False


def build_role_profile(
    preferred_roles: Sequence[str] | None,
    resume_titles: Sequence[str] | None = None,
    skills: Sequence[str] | None = None,
) -> RoleProfile:
    """Resolve the role universe from profile preferences, resume titles, then skills.

    Known IT families expand to related titles. Unknown (non-IT) roles keep the
    user's own wording for search/filter and never fall back to AI/ML defaults.
    """
    preferred = [str(role).strip() for role in (preferred_roles or []) if str(role).strip()]
    titles = [str(title).strip() for title in (resume_titles or []) if str(title).strip()]

    raw_roles: list[str] = []
    origin = "default"
    if preferred:
        raw_roles = preferred
        origin = "preferred_roles"
    elif titles:
        raw_roles = titles
        origin = "resume_titles"

    families: list[str] = []
    for role in raw_roles:
        for key in families_for_text(role):
            if key not in families:
                families.append(key)

    if not families and not raw_roles:
        inferred = families_for_skills(skills or [])
        if inferred:
            families = [family.key for family in ROLE_FAMILIES if family.key in inferred]
            origin = "resume_skills"

    # Only fall back to the original AI/ML defaults when the user gave no signal
    # at all — never when they stated a non-IT role we simply don't catalog.
    if not families and not raw_roles:
        families = list(DEFAULT_FAMILIES)
        origin = "default"

    ordered = _expand_related(families) if families else []
    raw_keywords = tuple(
        dict.fromkeys(normalise_title(role) for role in raw_roles if normalise_title(role))
    )
    return RoleProfile(
        families=tuple(ordered),
        raw_keywords=raw_keywords,
        search_queries=_build_search_queries(raw_roles, ordered),
        origin=origin,
    )


def build_role_profile_for_user(session, user) -> RoleProfile:
    """Build the role profile for a user, reading resume titles when preferences are empty."""
    resume_titles: list[str] = []
    if not (user.preferred_roles or []):
        resume_titles = active_resume_titles(session, user.id)
    return build_role_profile(
        preferred_roles=list(user.preferred_roles or []),
        resume_titles=resume_titles,
        skills=list(user.parsed_skills or []),
    )


def active_resume_titles(session, user_id) -> list[str]:
    """Return previous job titles parsed from the user's active master resume."""
    from sqlalchemy import select

    from db.models import MasterResume

    resume = session.scalar(
        select(MasterResume)
        .where(MasterResume.user_id == user_id, MasterResume.is_active.is_(True))
        .order_by(MasterResume.uploaded_at.desc())
        .limit(1)
    )
    if resume is None or not isinstance(resume.parsed_json, dict):
        return []
    titles = resume.parsed_json.get("previous_titles") or []
    return [str(title).strip() for title in titles if str(title).strip()]


def filter_jobs_by_role(jobs: list[dict], profile: RoleProfile | None) -> list[dict]:
    """Drop jobs whose title falls outside the user's target role universe."""
    if profile is None:
        return jobs
    return [job for job in jobs if profile.matches_title(job.get("title", ""))]
