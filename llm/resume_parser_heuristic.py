"""Rule-based resume parsing. No API calls, no cost."""

from __future__ import annotations

import re
from datetime import date

from api.schemas.resume import ParsedResumeOutput
from skills.known_skills import KNOWN_SKILLS

_TITLE_KEYWORDS = (
    "engineer",
    "developer",
    "scientist",
    "analyst",
    "architect",
    "manager",
    "lead",
    "director",
    "consultant",
    "specialist",
    "researcher",
    "intern",
    "designer",
    "administrator",
)

_EDUCATION_PATTERNS = [
    r"\b(?:ph\.?d|doctorate)\b",
    r"\b(?:m\.?s\.?c?|m\.?tech|master(?:'s)?)\b",
    r"\b(?:b\.?s\.?c?|b\.?tech|bachelor(?:'s)?)\b",
    r"\bmba\b",
    r"\b(?:b\.?e\.?|m\.?e\.?)\b",
]

_LANGUAGES = [
    "english",
    "hindi",
    "spanish",
    "french",
    "german",
    "mandarin",
    "chinese",
    "japanese",
    "korean",
    "portuguese",
    "arabic",
    "tamil",
    "telugu",
    "bengali",
    "marathi",
]


_SOFT_SKILLS = [
    "writing",
    "content writing",
    "research",
    "communication",
    "editing",
    "proofreading",
    "creative writing",
    "copywriting",
    "marketing",
    "social media",
    "public speaking",
    "presentation",
    "teamwork",
    "leadership",
    "project management",
    "data analysis",
    "microsoft office",
    "excel",
    "customer service",
]


def _extract_skills(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for skill in [*KNOWN_SKILLS, *_SOFT_SKILLS]:
        pattern = re.escape(skill).replace(r"\ ", r"\s+")
        if re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", lowered):
            label = skill.title() if skill.islower() and " " not in skill else skill
            if label not in found:
                found.append(label)
    return found


def _extract_skills_section_bullets(text: str) -> list[str]:
    """Pull bullet items listed under a Skills / Core competencies heading."""
    lines = text.splitlines()
    in_section = False
    found: list[str] = []
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower().rstrip(":")
        if lowered in {"skills", "core skills", "technical skills", "key skills", "competencies"}:
            in_section = True
            continue
        if in_section:
            if not stripped:
                if found:
                    break
                continue
            if stripped.endswith(":") and len(stripped) < 40 and stripped.count(" ") <= 4:
                break
            cleaned = re.sub(r"^[•\-\*\u2022]\s*", "", stripped).strip()
            if (
                cleaned
                and len(cleaned) <= 80
                and cleaned not in found
                and "|" not in cleaned
                and not any(
                    re.search(pattern, cleaned.lower())
                    for pattern in _EDUCATION_PATTERNS
                )
            ):
                found.append(cleaned)
    return found[:20]


def _extract_experience_years(text: str) -> int:
    explicit = re.search(
        r"(\d{1,2})\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)",
        text,
        re.IGNORECASE,
    )
    if explicit:
        return min(int(explicit.group(1)), 50)

    years = [int(match) for match in re.findall(r"\b(19|20)\d{2}\b", text)]
    if len(years) >= 2:
        span = date.today().year - min(years)
        return max(0, min(span, 50))
    if len(years) == 1:
        span = date.today().year - years[0]
        return max(0, min(span, 50))
    return 0


def _extract_titles(text: str) -> list[str]:
    titles: list[str] = []
    for line in text.splitlines():
        cleaned = line.strip(" •-\t")
        if not cleaned or len(cleaned) > 120:
            continue
        lowered = cleaned.lower()
        if any(keyword in lowered for keyword in _TITLE_KEYWORDS):
            if cleaned not in titles:
                titles.append(cleaned)
    return titles[:8]


def _extract_education(text: str) -> list[str]:
    education: list[str] = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(re.search(pattern, lowered) for pattern in _EDUCATION_PATTERNS):
            cleaned = line.strip()
            if cleaned and cleaned not in education:
                education.append(cleaned)
    return education[:5]


def _extract_languages(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for language in _LANGUAGES:
        if re.search(rf"\b{language}\b", lowered):
            found.append(language.title())
    return found


def parse_resume_heuristic(resume_text: str) -> ParsedResumeOutput:
    """Extract resume fields using keyword and pattern matching."""
    cleaned = resume_text.strip()
    skills = _extract_skills(cleaned)
    for bullet in _extract_skills_section_bullets(cleaned):
        if bullet not in skills:
            skills.append(bullet)
    return ParsedResumeOutput(
        skills=skills,
        experience_years=_extract_experience_years(cleaned),
        previous_titles=_extract_titles(cleaned),
        education=_extract_education(cleaned),
        languages=_extract_languages(cleaned),
    )
