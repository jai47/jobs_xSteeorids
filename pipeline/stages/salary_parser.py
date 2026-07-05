"""
F09a — deterministic salary parser over salary_display and JD text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SalaryPeriod = Literal["year", "month", "day", "hour"]

_HOURS_PER_YEAR = 2080
_DAYS_PER_YEAR = 260

# Non-salary phrases that must not parse as compensation.
_NEGATIVE_PATTERNS = re.compile(
    r"\b(competitive|negotiable|doe|commensurate|not disclosed|n/?a)\b",
    re.I,
)

# INR lakhs per annum — core audience pattern.
_LPA_PATTERN = re.compile(
    r"(?P<min>\d+(?:\.\d+)?)\s*(?:–|-|to)\s*(?P<max>\d+(?:\.\d+)?)\s*(?:lpa|lakhs?)\b",
    re.I,
)
_LPA_SINGLE = re.compile(r"(?:up to|upto|max(?:imum)?)\s*(?P<max>\d+(?:\.\d+)?)\s*(?:lpa|lakhs?)\b", re.I)
_LPA_ONE = re.compile(r"(?P<val>\d+(?:\.\d+)?)\s*(?:lpa|lakhs?)\b", re.I)

# Currency-prefixed ranges: €60,000–€80,000, $120k-$150k, £65k
_RANGE_PATTERN = re.compile(
    r"(?P<cur>[$€£]|USD|EUR|GBP|INR|SEK|CAD|AUD|SGD)?\s*"
    r"(?P<min>\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<min_k>k)?"
    r"\s*(?:–|-|to)\s*"
    r"(?P<cur2>[$€£]|USD|EUR|GBP|INR|SEK|CAD|AUD|SGD)?\s*"
    r"(?P<max>\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<max_k>k)?"
    r"(?:\s*/\s*(?P<period>yr|year|annum|month|mo|day|hour|hr))?",
    re.I,
)

_SINGLE_PATTERN = re.compile(
    r"(?P<cur>[$€£]|USD|EUR|GBP|INR|SEK|CAD|AUD|SGD)?\s*"
    r"(?P<val>\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<k>k)?"
    r"(?:\s*/\s*(?P<period>yr|year|annum|month|mo|day|hour|hr))?",
    re.I,
)

_CURRENCY_MAP = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "USD": "USD",
    "EUR": "EUR",
    "GBP": "GBP",
    "INR": "INR",
    "SEK": "SEK",
    "CAD": "CAD",
    "AUD": "AUD",
    "SGD": "SGD",
}

_COUNTRY_CURRENCY = {
    "US": "USD",
    "GB": "GBP",
    "UK": "GBP",
    "IN": "INR",
    "SE": "SEK",
    "CA": "CAD",
    "AU": "AUD",
    "SG": "SGD",
    "DE": "EUR",
    "FR": "EUR",
    "NL": "EUR",
}


@dataclass(frozen=True)
class SalaryParse:
    salary_min: int | None
    salary_max: int | None
    salary_currency: str
    salary_period: SalaryPeriod
    currency_assumed: bool = False


def _parse_amount(raw: str, is_k: bool = False) -> int:
    cleaned = raw.replace(",", "").replace(" ", "")
    value = float(cleaned)
    if is_k:
        value *= 1000
    return int(round(value))


def _resolve_currency(symbol: str | None, job_country: str | None) -> tuple[str, bool]:
    if symbol:
        cur = _CURRENCY_MAP.get(symbol.upper() if len(symbol) > 1 else symbol, symbol.upper())
        if cur in _CURRENCY_MAP.values():
            return cur, False
    if job_country:
        cc = job_country.upper()
        if cc in _COUNTRY_CURRENCY:
            return _COUNTRY_CURRENCY[cc], True
    return "USD", True


def _normalise_period(period: str | None) -> SalaryPeriod:
    if not period:
        return "year"
    p = period.lower()
    if p in ("mo", "month"):
        return "month"
    if p == "day":
        return "day"
    if p in ("hr", "hour"):
        return "hour"
    return "year"


def _annualise(amount: int, period: SalaryPeriod) -> int:
    if period == "year":
        return amount
    if period == "month":
        return amount * 12
    if period == "day":
        return amount * _DAYS_PER_YEAR
    return amount * _HOURS_PER_YEAR


def parse_salary(
    salary_display: str | None,
    description: str | None = None,
    *,
    job_country: str | None = None,
) -> SalaryParse | None:
    """Parse compensation from display string and optional JD fallback."""
    text = " ".join(filter(None, [salary_display, description])).strip()
    if not text or _NEGATIVE_PATTERNS.search(text):
        return None

    # INR LPA
    m = _LPA_PATTERN.search(text)
    if m:
        min_lakh = float(m.group("min"))
        max_lakh = float(m.group("max"))
        return SalaryParse(
            salary_min=int(min_lakh * 100_000),
            salary_max=int(max_lakh * 100_000),
            salary_currency="INR",
            salary_period="year",
        )

    m = _LPA_SINGLE.search(text)
    if m:
        max_lakh = float(m.group("max"))
        return SalaryParse(
            salary_min=None,
            salary_max=int(max_lakh * 100_000),
            salary_currency="INR",
            salary_period="year",
        )

    m = _LPA_ONE.search(text)
    if m and "lpa" in text.lower():
        val = float(m.group("val"))
        amount = int(val * 100_000)
        return SalaryParse(
            salary_min=amount,
            salary_max=amount,
            salary_currency="INR",
            salary_period="year",
        )

    for m in _RANGE_PATTERN.finditer(text):
        has_range_marker = bool(
            m.group("cur") or m.group("cur2") or m.group("min_k") or m.group("max_k") or m.group("period")
        )
        if not has_range_marker:
            # Bare numeric range with no currency/k/period marker, e.g. "3-5 years
            # of experience" — not a salary, keep scanning for a qualifying match.
            continue
        currency, assumed = _resolve_currency(m.group("cur") or m.group("cur2"), job_country)
        period = _normalise_period(m.group("period"))
        sal_min = _annualise(_parse_amount(m.group("min"), bool(m.group("min_k"))), period)
        sal_max = _annualise(_parse_amount(m.group("max"), bool(m.group("max_k"))), period)
        return SalaryParse(
            salary_min=min(sal_min, sal_max),
            salary_max=max(sal_min, sal_max),
            salary_currency=currency,
            salary_period="year",
            currency_assumed=assumed,
        )

    m = _SINGLE_PATTERN.search(text)
    if m and any(c in text for c in ("$", "€", "£", "k", "K", "/yr", "/year", "/hour", "/hr")):
        currency, assumed = _resolve_currency(m.group("cur"), job_country)
        period = _normalise_period(m.group("period"))
        amount = _annualise(_parse_amount(m.group("val"), bool(m.group("k"))), period)
        return SalaryParse(
            salary_min=amount,
            salary_max=amount,
            salary_currency=currency,
            salary_period="year",
            currency_assumed=assumed,
        )

    return None
