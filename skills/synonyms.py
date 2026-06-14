"""Skill synonym normalisation (used in Phase 7 fit scoring)."""

from __future__ import annotations

SKILL_SYNONYMS: dict[str, str] = {
    "scikit learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "tf": "tensorflow",
    "k8s": "kubernetes",
    "huggingface": "hugging face",
    "hf": "hugging face",
    "generativeai": "generative ai",
    "machine learning": "ml",
    "ml": "ml",
    "py torch": "pytorch",
    "postgres": "postgres",
    "postgresql": "postgres",
    "gcp": "gcp",
    "google cloud": "gcp",
    "amazon web services": "aws",
}


def normalise_skill(skill: str) -> str:
    """Return the canonical skill name for a raw token."""
    cleaned = skill.strip().lower()
    return SKILL_SYNONYMS.get(cleaned, cleaned)
