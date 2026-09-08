"""
Rule-based fit scoring.
fit_score = skill(40%) + role(25%) + experience(20%) + country(10%) + remote(5%)
"""

from __future__ import annotations

from typing import TypedDict

from pipeline.role_targets import (
    families_for_text,
    normalise_title as normalise_role_title,
    primary_family_for,
    title_matches_custom_roles,
)
from services.job_taste import compute_taste_boost
from skills.synonyms import normalise_skill


class FitScoreResult(TypedDict):
    score_skill_match: float
    score_role_match: float
    score_experience: float
    score_country_pref: float
    score_remote_pref: float
    score_fit: float
    fit_reasoning: str


# Role match is scored against the shared role-family taxonomy so a title the
# user never targets cannot quietly score the same as one they did.
ROLE_MATCH_EXACT = 100.0
ROLE_MATCH_NO_PREFERENCE = 60.0
ROLE_MATCH_UNKNOWN_TITLE = 45.0
ROLE_MATCH_WRONG_FAMILY = 10.0


def _preferred_role_match(job_title: str, preferred_roles: list[str]) -> bool:
    """True when the job title matches a preferred role by phrase or distinctive token."""
    normalised = normalise_role_title(job_title)
    keywords = [normalise_role_title(role) for role in preferred_roles if str(role).strip()]
    keywords = [keyword for keyword in keywords if keyword]
    if not keywords:
        return False
    if any(f" {keyword} " in f" {normalised} " for keyword in keywords):
        return True
    return title_matches_custom_roles(normalised, keywords)


def _score_role(job_title: str, preferred_roles: list[str]) -> tuple[float, str]:
    cleaned_prefs = [role for role in preferred_roles if str(role).strip()]
    user_families: set[str] = set()
    for role in cleaned_prefs:
        user_families |= families_for_text(role)

    if not cleaned_prefs:
        return ROLE_MATCH_NO_PREFERENCE, "no role preference on file"

    if _preferred_role_match(job_title, cleaned_prefs):
        return ROLE_MATCH_EXACT, "matches preference"

    job_family = primary_family_for(job_title)
    if user_families:
        if job_family is not None and job_family in user_families:
            return ROLE_MATCH_EXACT, "matches preference"
        return ROLE_MATCH_WRONG_FAMILY, "different role family than preferred"

    # Non-IT preferences: anything that doesn't match their wording is a miss.
    return ROLE_MATCH_WRONG_FAMILY, "does not match preferred roles"


def score_fit(job: dict, user) -> FitScoreResult:
    """Compute deterministic fit score between a job and user profile."""
    required = {normalise_skill(skill) for skill in job.get("skills_required", [])}
    user_skills = {normalise_skill(skill) for skill in (user.parsed_skills or [])}

    if required:
        matched = required & user_skills
        skill_match = len(matched) / len(required) * 100
    else:
        skill_match = 50.0

    role_match, role_reason = _score_role(
        job.get("title", ""), list(user.preferred_roles or [])
    )

    job_exp = job.get("experience_min") or 0
    user_exp = user.years_experience or 0
    gap = user_exp - job_exp
    if gap >= 0:
        exp_match = 100.0
    elif gap >= -1:
        exp_match = 75.0
    elif gap >= -2:
        exp_match = 40.0
    else:
        exp_match = 0.0

    job_country = (job.get("country") or "").upper()
    preferred_countries = [country.upper() for country in (user.preferred_countries or [])]
    if job_country in preferred_countries:
        country_pref = 100.0
    elif job.get("remote_type") == "remote":
        country_pref = 70.0
    else:
        country_pref = 0.0

    if user.prefers_remote and job.get("remote_type") in ("remote", "hybrid"):
        remote_pref = 100.0
    elif not user.prefers_remote and job.get("remote_type") == "onsite":
        remote_pref = 100.0
    else:
        remote_pref = 50.0

    fit_score = (
        skill_match * 0.40
        + role_match * 0.25
        + exp_match * 0.20
        + country_pref * 0.10
        + remote_pref * 0.05
    )
    taste_boost = compute_taste_boost(job, user)
    if taste_boost:
        fit_score = max(0.0, min(100.0, fit_score + taste_boost))

    matched_list = list(required & user_skills)[:5]
    reasoning = (
        f"Skills: {len(required & user_skills)}/{len(required)} matched"
        f"{' (' + ', '.join(matched_list) + ')' if matched_list else ''}. "
        f"Role: {role_reason}. "
        f"Experience: {user_exp}yrs vs {job_exp} required."
    )
    if taste_boost:
        reasoning += f" Taste: {taste_boost:+.0f} from past feedback."

    return {
        "score_skill_match": round(skill_match, 1),
        "score_role_match": round(role_match, 1),
        "score_experience": round(exp_match, 1),
        "score_country_pref": round(country_pref, 1),
        "score_remote_pref": round(remote_pref, 1),
        "score_fit": round(fit_score, 1),
        "fit_reasoning": reasoning,
    }
