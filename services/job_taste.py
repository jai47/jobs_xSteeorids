"""Learn job preferences from approve / skip / reject feedback.

Taste signals live in ``user.autopilot["job_taste"]`` so we avoid a migration
while still personalising search queries and fit scoring on later runs.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from pipeline.role_targets import distinctive_tokens, normalise_title

_TASTE_KEY = "job_taste"
_MAX_TRACKED = 40
_TOKEN_RE = re.compile(r"[a-z0-9]{4,}")


def empty_taste() -> dict[str, Any]:
    return {
        "liked_companies": {},
        "disliked_companies": {},
        "liked_title_tokens": {},
        "disliked_title_tokens": {},
        "liked_titles": [],
        "liked_archetypes": {},
        "disliked_archetypes": {},
    }


def get_job_taste(user) -> dict[str, Any]:
    autopilot = user.autopilot if isinstance(getattr(user, "autopilot", None), dict) else {}
    taste = autopilot.get(_TASTE_KEY)
    if not isinstance(taste, dict):
        return empty_taste()
    merged = empty_taste()
    for key, default in merged.items():
        value = taste.get(key)
        if isinstance(default, dict) and isinstance(value, dict):
            merged[key] = {str(k): int(v) for k, v in value.items() if str(k).strip()}
        elif isinstance(default, list) and isinstance(value, list):
            merged[key] = [str(v).strip() for v in value if str(v).strip()][:12]
    return merged


def _bump(counter: dict[str, int], key: str, delta: int = 1) -> None:
    cleaned = (key or "").strip()
    if not cleaned:
        return
    counter[cleaned] = int(counter.get(cleaned, 0)) + delta
    if counter[cleaned] <= 0:
        counter.pop(cleaned, None)


def _trim_counter(counter: dict[str, int], limit: int = _MAX_TRACKED) -> dict[str, int]:
    if len(counter) <= limit:
        return counter
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))
    return dict(ranked[:limit])


def _title_tokens(title: str) -> list[str]:
    tokens = list(distinctive_tokens(title))
    if tokens:
        return tokens
    return [tok for tok in _TOKEN_RE.findall(normalise_title(title))][:6]


def record_opportunity_feedback(
    user,
    job,
    *,
    feedback: str,
    reject_reason: str | None = None,
) -> dict[str, Any]:
    """Update the user's job taste from an opportunity action and persist it."""
    taste = get_job_taste(user)
    company = (getattr(job, "company", None) or "").strip()
    title = (getattr(job, "title", None) or "").strip()
    archetype = (getattr(job, "archetype", None) or "").strip()
    tokens = _title_tokens(title)

    if feedback == "approved":
        _bump(taste["liked_companies"], company, 2)
        _bump(taste["liked_archetypes"], archetype, 2)
        for token in tokens:
            _bump(taste["liked_title_tokens"], token, 2)
        if title:
            liked = [title] + [t for t in taste["liked_titles"] if t.lower() != title.lower()]
            taste["liked_titles"] = liked[:8]
        # Approving cancels prior dislike for the same company.
        taste["disliked_companies"].pop(company, None)

    elif feedback == "rejected":
        if reject_reason == "company":
            _bump(taste["disliked_companies"], company, 3)
        elif reject_reason == "role":
            for token in tokens:
                _bump(taste["disliked_title_tokens"], token, 3)
            _bump(taste["disliked_archetypes"], archetype, 2)
        else:
            _bump(taste["disliked_companies"], company, 1)
            for token in tokens:
                _bump(taste["disliked_title_tokens"], token, 1)

    elif feedback == "skipped":
        _bump(taste["disliked_companies"], company, 1)
        for token in tokens:
            _bump(taste["disliked_title_tokens"], token, 1)

    taste["liked_companies"] = _trim_counter(taste["liked_companies"])
    taste["disliked_companies"] = _trim_counter(taste["disliked_companies"])
    taste["liked_title_tokens"] = _trim_counter(taste["liked_title_tokens"])
    taste["disliked_title_tokens"] = _trim_counter(taste["disliked_title_tokens"])
    taste["liked_archetypes"] = _trim_counter(taste["liked_archetypes"])
    taste["disliked_archetypes"] = _trim_counter(taste["disliked_archetypes"])

    autopilot = dict(user.autopilot) if isinstance(getattr(user, "autopilot", None), dict) else {}
    autopilot[_TASTE_KEY] = taste
    user.autopilot = autopilot
    try:
        flag_modified(user, "autopilot")
    except Exception:
        # Plain namespace objects in unit tests are not SQLAlchemy mapped.
        pass
    return taste


def taste_search_queries(user, *, limit: int = 4) -> list[str]:
    """Extra discovery queries derived from titles the user approved."""
    taste = get_job_taste(user)
    queries: list[str] = []
    for title in taste.get("liked_titles") or []:
        cleaned = normalise_title(title)
        if cleaned and cleaned not in queries:
            queries.append(cleaned)
    # Fall back to strongest liked tokens as soft queries.
    tokens = sorted(
        (taste.get("liked_title_tokens") or {}).items(),
        key=lambda item: (-item[1], item[0]),
    )
    for token, _count in tokens:
        if token not in queries and len(token) >= 5:
            queries.append(token)
        if len(queries) >= limit:
            break
    return queries[:limit]


def compute_taste_boost(job: dict, user) -> float:
    """Return a fit-score adjustment in roughly [-15, +15] from past feedback."""
    taste = get_job_taste(user)
    company = (job.get("company") or "").strip()
    title = job.get("title") or ""
    archetype = (job.get("archetype") or "").strip()
    tokens = set(_title_tokens(title))

    score = 0.0
    liked_co = int((taste.get("liked_companies") or {}).get(company, 0))
    disliked_co = int((taste.get("disliked_companies") or {}).get(company, 0))
    score += min(liked_co, 4) * 2.5
    score -= min(disliked_co, 4) * 3.0

    liked_tokens = taste.get("liked_title_tokens") or {}
    disliked_tokens = taste.get("disliked_title_tokens") or {}
    for token in tokens:
        score += min(int(liked_tokens.get(token, 0)), 3) * 1.5
        score -= min(int(disliked_tokens.get(token, 0)), 3) * 2.0

    if archetype:
        score += min(int((taste.get("liked_archetypes") or {}).get(archetype, 0)), 3) * 1.5
        score -= min(int((taste.get("disliked_archetypes") or {}).get(archetype, 0)), 3) * 2.0

    return max(-15.0, min(15.0, score))
