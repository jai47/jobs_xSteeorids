"""Text extraction helpers for job descriptions and salary parsing."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

from skills.known_skills import KNOWN_SKILLS

VISA_KEYWORDS = [
    "visa sponsorship",
    "will sponsor visa",
    "sponsorship provided",
    "we sponsor",
    "visa support",
    "relocation support",
    "relocation assistance",
    "relocation package",
    "work permit",
    "right to work",
    "employment pass",
    "skilled worker visa",
    "tier 2 sponsor",
    "eu blue card",
    "h-1b",
    "employment visa india",
    "pan india",
    "work from india",
    "india based",
    "open to relocation",
    "global team",
    "international candidates welcome",
    "must be authorised to work",
    "no visa sponsorship",
    "citizens and permanent residents only",
    "no relocation",
    "indian nationals only",
]

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
CURRENCY_CODES = {"USD", "EUR", "GBP", "INR", "SGD", "AED", "CAD", "AUD"}

COUNTRY_ALIASES = {
    "united states": "US",
    "usa": "US",
    "u.s.": "US",
    "us": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "england": "GB",
    "scotland": "GB",
    "germany": "DE",
    "netherlands": "NL",
    "holland": "NL",
    "singapore": "SG",
    "india": "IN",
    "canada": "CA",
    "australia": "AU",
    "france": "FR",
    "switzerland": "CH",
    "sweden": "SE",
    "ireland": "IE",
    "uae": "AE",
    "united arab emirates": "AE",
}

SALARY_PATTERNS = [
    re.compile(
        r"([$€£₹])\s*(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\s*(k|K|L|LPA)?\s*[-–—to]+\s*([$€£₹])?\s*(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\s*(k|K|L|LPA)?",
    ),
    re.compile(
        r"(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\s*(k|K|L|LPA)?\s*[-–—to]+\s*(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\s*(k|K|L|LPA)?\s*(USD|EUR|GBP|INR|SGD|AED|CAD|AUD)",
        re.IGNORECASE,
    ),
    re.compile(
        r"([$€£₹])\s*(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\s*(k|K|L|LPA)?",
    ),
]

EXPERIENCE_PATTERNS = [
    re.compile(r"(\d+)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience", re.IGNORECASE),
    re.compile(r"minimum\s+(\d+)\s+years?", re.IGNORECASE),
    re.compile(r"at least\s+(\d+)\s+years?", re.IGNORECASE),
]


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data.strip())

    def get_text(self) -> str:
        return "\n".join(self._parts)


def strip_html(html: str) -> str:
    """Convert HTML content to plain text."""
    if not html:
        return ""
    parser = _HTMLTextExtractor()
    parser.feed(unescape(html))
    parser.close()
    return parser.get_text()


def extract_visa_keywords(description: str) -> list[str]:
    """Return visa-related keywords found in a job description."""
    desc_lower = description.lower()
    return [kw for kw in VISA_KEYWORDS if kw in desc_lower]


def extract_skills(description: str) -> list[str]:
    """Return known skills mentioned in a job description."""
    desc_lower = description.lower()
    return [skill for skill in KNOWN_SKILLS if skill in desc_lower]


def _normalise_amount(raw: str, suffix: str | None) -> int:
    cleaned = raw.replace(",", "").replace(".", "")
    value = int(float(cleaned)) if cleaned.isdigit() else int(float(raw.replace(",", "")))
    if suffix and suffix.upper() in {"K"}:
        return value * 1000
    if suffix and suffix.upper() in {"L", "LPA"}:
        return value * 100000
    if value < 1000 and suffix is None and value < 500:
        return value * 1000
    return value


def extract_salary_display(description: str) -> str | None:
    """Extract the first salary-like string from a description."""
    for pattern in SALARY_PATTERNS:
        match = pattern.search(description)
        if match:
            return match.group(0).strip()
    return None


def parse_salary_range(salary_display: str | None) -> dict[str, int | str] | None:
    """
    Attempt to extract (min, max, currency) from a salary display string.
    Returns None if unparseable. No forex conversion.
    """
    if not salary_display:
        return None

    text = salary_display.strip()

    symbol_match = re.search(
        r"([$€£₹])\s*(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\s*(k|K|L|LPA)?\s*[-–—to]+\s*([$€£₹])?\s*(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\s*(k|K|L|LPA)?",
        text,
        re.IGNORECASE,
    )
    if symbol_match:
        symbol = symbol_match.group(1)
        currency = CURRENCY_SYMBOLS.get(symbol, "USD")
        min_val = _normalise_amount(symbol_match.group(2), symbol_match.group(3))
        max_val = _normalise_amount(symbol_match.group(5), symbol_match.group(6))
        return {"min": min_val, "max": max_val, "currency": currency}

    code_match = re.search(
        r"(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\s*(k|K|L|LPA)?\s*[-–—to]+\s*(\d{1,3}(?:[.,]\d{3})*(?:\.\d+)?)\s*(k|K|LPA)?\s*(USD|EUR|GBP|INR|SGD|AED|CAD|AUD)",
        text,
        re.IGNORECASE,
    )
    if code_match:
        currency = code_match.group(6).upper()
        return {
            "min": _normalise_amount(code_match.group(1), code_match.group(2)),
            "max": _normalise_amount(code_match.group(3), code_match.group(4)),
            "currency": currency,
        }

    lpa_match = re.search(
        r"(\d{1,2})\s*LPA\s*[-–—to]+\s*(\d{1,2})\s*LPA",
        text,
        re.IGNORECASE,
    )
    if lpa_match:
        return {
            "min": int(lpa_match.group(1)) * 100000,
            "max": int(lpa_match.group(2)) * 100000,
            "currency": "INR",
        }

    inr_symbol_match = re.search(
        r"₹\s*(\d{1,2})\s*L\s*[-–—to]+\s*₹\s*(\d{1,2})\s*L",
        text,
        re.IGNORECASE,
    )
    if inr_symbol_match:
        return {
            "min": int(inr_symbol_match.group(1)) * 100000,
            "max": int(inr_symbol_match.group(2)) * 100000,
            "currency": "INR",
        }

    return None


def parse_remote_type(location: str | None) -> str | None:
    """Infer remote/hybrid/onsite from a location string."""
    if not location:
        return None
    lowered = location.lower()
    if "remote" in lowered:
        return "remote"
    if "hybrid" in lowered:
        return "hybrid"
    return "onsite"


def parse_country_and_city(location: str | None) -> tuple[str | None, str | None]:
    """Best-effort ISO-2 country and city extraction from a location string."""
    if not location:
        return None, None

    lowered = location.lower().strip()
    if lowered.startswith("remote"):
        for alias, code in COUNTRY_ALIASES.items():
            if alias in lowered:
                return code, None
        return None, None

    parts = [part.strip() for part in re.split(r"[,/|-]", location) if part.strip()]
    country = None
    city = None

    for part in reversed(parts):
        alias = part.lower()
        if alias in COUNTRY_ALIASES:
            country = COUNTRY_ALIASES[alias]
            break
        if len(part) == 2 and part.isalpha():
            country = part.upper()
            break

    if parts:
        city = parts[0]

    return country, city


def extract_experience_min(description: str) -> int | None:
    """Extract minimum years of experience from a job description."""
    for pattern in EXPERIENCE_PATTERNS:
        match = pattern.search(description)
        if match:
            return int(match.group(1))
    return None
