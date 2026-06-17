"""
Rule-based visa scoring engine.
Three signal layers: keywords, country base rate, company size.
Output: visa_score (0-100), visa_status, visa_reasoning
"""

from __future__ import annotations

from typing import TypedDict


class VisaScoreResult(TypedDict):
    score_visa: int
    visa_status: str
    visa_reasoning: str


TIER_A_KEYWORDS = [
    "visa sponsorship",
    "will sponsor visa",
    "sponsorship provided",
    "we sponsor",
    "visa support",
]

TIER_B_KEYWORDS = [
    "relocation support",
    "relocation assistance",
    "relocation package",
    "work permit",
    "right to work support",
    "employment pass",
    "skilled worker visa",
    "tier 2 sponsor",
    "eu blue card",
    "h-1b",
    "employment visa india",
]

TIER_C_KEYWORDS = [
    "open to relocation",
    "global team",
    "international candidates welcome",
    "pan india",
    "work from india",
    "india based",
]

NEGATIVE_KEYWORDS = [
    "must be authorised to work",
    "must be authorized to work",
    "no visa sponsorship",
    "citizens and permanent residents only",
    "no relocation",
    "indian nationals only",
]

COUNTRY_BASE_RATES = {
    "SG": 70,
    "AE": 70,
    "NL": 65,
    "DE": 60,
    "CA": 60,
    "IN": 55,
    "AU": 55,
    "UK": 50,
    "GB": 50,
    "US": 35,
}
DEFAULT_BASE_RATE = 25

LARGE_SIGNALS = [
    "series b",
    "series c",
    "series d",
    "series e",
    "500+ employees",
    "enterprise",
    "publicly traded",
    "fortune 500",
]
SMALL_SIGNALS = [
    "seed stage",
    "early stage",
    "5-person team",
    "pre-seed",
    "bootstrapped",
    "founding team",
]


def score_visa(job: dict, user=None) -> VisaScoreResult:
    """Compute deterministic visa sponsorship likelihood for a job posting."""
    desc = job.get("description", "").lower()
    country_code = (job.get("country") or "").upper()

    user_nationality = (getattr(user, "nationality", None) or "").upper()
    if user_nationality and country_code == user_nationality:
        return {
            "score_visa": 100,
            "visa_status": "available",
            "visa_reasoning": f"Home country ({country_code}). No visa required.",
        }

    tier_a_pts = min(50, sum(25 for kw in TIER_A_KEYWORDS if kw in desc))
    tier_b_pts = min(30, sum(15 for kw in TIER_B_KEYWORDS if kw in desc))
    tier_c_pts = min(16, sum(8 for kw in TIER_C_KEYWORDS if kw in desc))
    neg_pts = sum(-20 for kw in NEGATIVE_KEYWORDS if kw in desc)
    keyword_score = tier_a_pts + tier_b_pts + tier_c_pts + neg_pts

    matched_kws = [
        kw
        for kw in (TIER_A_KEYWORDS + TIER_B_KEYWORDS + TIER_C_KEYWORDS)
        if kw in desc
    ]
    neg_kws = [kw for kw in NEGATIVE_KEYWORDS if kw in desc]

    base_rate = COUNTRY_BASE_RATES.get(country_code, DEFAULT_BASE_RATE)

    size_adj = 0
    size_signal = "none"
    if any(signal in desc for signal in LARGE_SIGNALS):
        size_adj = 8
        size_signal = "large/growth-stage"
    elif any(signal in desc for signal in SMALL_SIGNALS):
        size_adj = -10
        size_signal = "early-stage"

    raw = base_rate + keyword_score + size_adj
    visa_score = max(0, min(100, raw))

    if visa_score >= 70:
        visa_status = "available"
    elif visa_score >= 50:
        visa_status = "likely"
    elif visa_score >= 30:
        visa_status = "unknown"
    elif visa_score >= 15:
        visa_status = "unlikely"
    else:
        visa_status = "none"

    reasoning_parts = [f"Country base: {country_code or '??'} ({base_rate}pts)"]
    if matched_kws:
        reasoning_parts.append(
            f"Keywords: {', '.join(matched_kws[:3])} (+{keyword_score}pts)"
        )
    if neg_kws:
        reasoning_parts.append(f"Negative: {', '.join(neg_kws)} ({neg_pts}pts)")
    if size_signal != "none":
        sign = "+" if size_adj > 0 else ""
        reasoning_parts.append(f"Company size: {size_signal} ({sign}{size_adj}pts)")
    visa_reasoning = ". ".join(reasoning_parts) + "."

    return {
        "score_visa": visa_score,
        "visa_status": visa_status,
        "visa_reasoning": visa_reasoning,
    }
