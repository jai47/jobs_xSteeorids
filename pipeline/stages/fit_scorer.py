"""
Rule-based fit scoring.
fit_score = skill(40%) + role(25%) + experience(20%) + country(10%) + remote(5%)
"""

from __future__ import annotations

from typing import TypedDict

from skills.synonyms import normalise_skill


class FitScoreResult(TypedDict):
    score_skill_match: float
    score_role_match: float
    score_experience: float
    score_country_pref: float
    score_remote_pref: float
    score_fit: float
    fit_reasoning: str


ROLE_GROUPS: dict[str, list[str]] = {
    "ml_engineer": ["machine learning engineer", "ml engineer", "applied ml"],
    "ai_engineer": ["ai engineer", "artificial intelligence engineer", "applied ai"],
    "data_scientist": ["data scientist", "senior data scientist", "staff data scientist"],
    "cv_engineer": ["computer vision engineer", "cv engineer"],
    "llm_engineer": ["llm engineer", "llm researcher", "generative ai engineer"],
    "ai_platform": ["ai platform engineer", "ml platform", "ml infrastructure"],
}


def _role_group(title: str) -> str | None:
    lowered = title.lower()
    for group, variants in ROLE_GROUPS.items():
        if any(variant in lowered for variant in variants):
            return group
    return None


def score_fit(job: dict, user) -> FitScoreResult:
    """Compute deterministic fit score between a job and user profile."""
    required = {normalise_skill(skill) for skill in job.get("skills_required", [])}
    user_skills = {normalise_skill(skill) for skill in (user.parsed_skills or [])}

    if required:
        matched = required & user_skills
        skill_match = len(matched) / len(required) * 100
    else:
        skill_match = 50.0

    job_group = _role_group(job.get("title", ""))
    user_groups = [_role_group(role) for role in (user.preferred_roles or [])]
    role_match = 100.0 if job_group and job_group in user_groups else 40.0

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

    matched_list = list(required & user_skills)[:5]
    reasoning = (
        f"Skills: {len(required & user_skills)}/{len(required)} matched"
        f"{' (' + ', '.join(matched_list) + ')' if matched_list else ''}. "
        f"Role: {'matches preference' if role_match == 100 else 'partial match'}. "
        f"Experience: {user_exp}yrs vs {job_exp} required."
    )

    return {
        "score_skill_match": round(skill_match, 1),
        "score_role_match": round(role_match, 1),
        "score_experience": round(exp_match, 1),
        "score_country_pref": round(country_pref, 1),
        "score_remote_pref": round(remote_pref, 1),
        "score_fit": round(fit_score, 1),
        "fit_reasoning": reasoning,
    }
