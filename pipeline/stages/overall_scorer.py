"""
overall_score = fit_score × 0.65 + visa_score × 0.35

Country preference is already inside fit_score (10% weight).
No separate location component. No double-counting.
"""

from __future__ import annotations

from typing import TypedDict


class OverallScoreResult(TypedDict):
    overall_score: float
    classification: str


DIGEST_MIN_SCORE = 70.0


def score_overall(fit_result: dict, visa_result: dict) -> OverallScoreResult:
    """Combine fit and visa scores into an overall classification."""
    fit = fit_result["score_fit"]
    visa = visa_result["score_visa"]

    overall = round(fit * 0.65 + visa * 0.35, 1)

    if overall >= 90:
        classification = "apply_immediately"
    elif overall >= 80:
        classification = "high_priority"
    elif overall >= 70:
        classification = "apply"
    elif overall >= 60:
        classification = "optional"
    else:
        classification = "skip"

    return {
        "overall_score": overall,
        "classification": classification,
    }


def is_digest_eligible(overall_score: float) -> bool:
    """Return True when an opportunity should appear in the daily digest."""
    return overall_score >= DIGEST_MIN_SCORE
