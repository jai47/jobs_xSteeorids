"""Canonical STAR story / interview theme tags (~25)."""

from __future__ import annotations

CANONICAL_STAR_TAGS: frozenset[str] = frozenset(
    {
        "ambiguity",
        "stakeholder_mgmt",
        "conflict",
        "leadership",
        "cross_functional",
        "technical_depth",
        "communication",
        "problem_solving",
        "prioritization",
        "deadline_pressure",
        "failure_recovery",
        "innovation",
        "mentorship",
        "teamwork",
        "ownership",
        "data_driven",
        "customer_focus",
        "adaptability",
        "negotiation",
        "ethics",
        "remote_collaboration",
        "project_management",
        "learning_agility",
        "influence_without_authority",
        "quality_focus",
    }
)

CANONICAL_TAG_LIST: list[str] = sorted(CANONICAL_STAR_TAGS)


def validate_tags(tags: list[str]) -> list[str]:
    """Return normalised tags; raise ValueError if any tag is not canonical."""
    normalised: list[str] = []
    for tag in tags:
        key = tag.strip().lower().replace(" ", "_").replace("-", "_")
        if key not in CANONICAL_STAR_TAGS:
            raise ValueError(f"Unknown tag: {tag}")
        if key not in normalised:
            normalised.append(key)
    return normalised
