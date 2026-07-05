"""F05 — Application response-rate analytics (SQL aggregates, 10-min cache)."""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from db.models import Application, ApplicationStageEvent, Job, ScoredOpportunity, User

UNLOCK_THRESHOLD = 10
CACHE_TTL_SECONDS = 600

RESPONSE_STATUSES = frozenset({"interviewing", "offer", "accepted", "rejected"})
QUALIFYING_STATUSES = frozenset({"applied", "interviewing", "offer", "accepted", "rejected"})

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _grade_band(score: float | None) -> str:
    if score is None:
        return "?"
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _percentile(sorted_values: list[int], pct: float) -> int | None:
    if not sorted_values:
        return None
    idx = int(round((pct / 100.0) * (len(sorted_values) - 1)))
    return sorted_values[max(0, min(idx, len(sorted_values) - 1))]


def _bulk_latest_scores(
    session: Session, user_id: uuid.UUID, job_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float | None]:
    """One query for the latest overall_score per job_id, instead of one query per row."""
    if not job_ids:
        return {}
    rows = (
        session.query(ScoredOpportunity)
        .filter(ScoredOpportunity.user_id == user_id, ScoredOpportunity.job_id.in_(job_ids))
        .order_by(ScoredOpportunity.job_id, ScoredOpportunity.created_at.desc())
        .all()
    )
    latest: dict[uuid.UUID, float | None] = {}
    for row in rows:
        latest.setdefault(row.job_id, row.overall_score)
    return latest


def _bulk_stage_events(
    session: Session, application_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ApplicationStageEvent]]:
    """One query for all stage events of the qualifying applications, grouped and time-ordered."""
    if not application_ids:
        return {}
    rows = (
        session.query(ApplicationStageEvent)
        .filter(ApplicationStageEvent.application_id.in_(application_ids))
        .order_by(ApplicationStageEvent.application_id, ApplicationStageEvent.occurred_at.asc())
        .all()
    )
    by_app: dict[uuid.UUID, list[ApplicationStageEvent]] = {}
    for row in rows:
        by_app.setdefault(row.application_id, []).append(row)
    return by_app


def _load_qualifying_rows(
    session: Session,
    user: User,
    *,
    date_from: date | None,
    date_to: date | None,
) -> list[dict[str, Any]]:
    rows = (
        session.query(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .filter(
            Application.user_id == user.id,
            Application.status.in_(QUALIFYING_STATUSES),
            Application.applied_at.isnot(None),
        )
        .all()
    )

    job_ids = [job.id for _app, job in rows]
    application_ids = [app.id for app, _job in rows]
    scores_by_job = _bulk_latest_scores(session, user.id, job_ids)
    events_by_app = _bulk_stage_events(session, application_ids)

    result: list[dict[str, Any]] = []
    for app, job in rows:
        applied = app.applied_at
        if applied is None:
            continue
        applied_date = applied.date() if hasattr(applied, "date") else applied
        if date_from and applied_date < date_from:
            continue
        if date_to and applied_date > date_to:
            continue

        events = events_by_app.get(app.id, [])
        applied_event = next((e for e in events if e.to_status == "applied"), None)
        response_event = next(
            (e for e in events if e.from_status == "applied" and e.to_status in RESPONSE_STATUSES),
            None,
        )
        response_at = response_event.occurred_at if response_event else None
        has_response = response_at is not None or app.status in RESPONSE_STATUSES
        has_applied_event = applied_event is not None
        applied_at = applied_event.occurred_at if applied_event else app.applied_at

        result.append(
            {
                "application_id": app.id,
                "country": (job.country or "Unknown").upper(),
                "archetype": job.archetype or "other",
                "score_band": _grade_band(scores_by_job.get(job.id)),
                "has_response": has_response,
                "has_applied_event": has_applied_event,
                "applied_at": applied_at,
                "response_at": response_at,
            }
        )
    return result


def _aggregate_bucket(rows: list[dict], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        k = row[key]
        if k not in buckets:
            buckets[k] = {"applications": 0, "responses": 0}
        buckets[k]["applications"] += 1
        if row["has_response"]:
            buckets[k]["responses"] += 1
    out: list[dict[str, Any]] = []
    for k in sorted(buckets.keys()):
        apps = buckets[k]["applications"]
        resp = buckets[k]["responses"]
        out.append(
            {
                "key": k,
                "applications": apps,
                "responses": resp,
                "rate": round(resp / apps, 4) if apps else 0.0,
            }
        )
    return out


def compute_application_analytics(
    session: Session,
    user: User,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    rows = _load_qualifying_rows(session, user, date_from=date_from, date_to=date_to)
    qualifying = len(rows)

    if qualifying < UNLOCK_THRESHOLD:
        return {
            "unlocked": False,
            "qualifying_applications": qualifying,
            "required": UNLOCK_THRESHOLD,
        }

    responses = sum(1 for r in rows if r["has_response"])
    excluded = sum(1 for r in rows if not r["has_applied_event"])

    day_counts: list[int] = []
    for row in rows:
        if not row["has_response"] or not row["has_applied_event"]:
            continue
        applied = row["applied_at"]
        responded = row["response_at"]
        if applied is None or responded is None:
            continue
        if applied.tzinfo is None:
            applied = applied.replace(tzinfo=timezone.utc)
        if responded.tzinfo is None:
            responded = responded.replace(tzinfo=timezone.utc)
        delta = responded - applied
        day_counts.append(max(delta.days, 0))

    day_counts.sort()
    sample_size = len(day_counts)

    return {
        "unlocked": True,
        "qualifying_applications": qualifying,
        "response_rate_overall": round(responses / qualifying, 4) if qualifying else 0.0,
        "by_country": _aggregate_bucket(rows, "country"),
        "by_archetype": _aggregate_bucket(rows, "archetype"),
        "by_score_band": _aggregate_bucket(rows, "score_band"),
        "days_to_first_response": {
            "p50": _percentile(day_counts, 50),
            "p90": _percentile(day_counts, 90),
            "sample_size": sample_size,
        },
        "excluded_pre_event_log": excluded,
    }


def get_application_analytics_cached(
    session: Session,
    user: User,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    cache_key = f"{user.id}:{date_from}:{date_to}"
    now = time.time()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    result = compute_application_analytics(
        session, user, date_from=date_from, date_to=date_to
    )
    _prune_expired(now)
    _cache[cache_key] = (now, result)
    return result


def _prune_expired(now: float) -> None:
    """Sweep expired entries so the cache doesn't grow without bound across distinct
    date-range keys — called on every write so the dict never holds more than the
    entries active within the last CACHE_TTL_SECONDS."""
    expired = [key for key, (ts, _val) in _cache.items() if now - ts >= CACHE_TTL_SECONDS]
    for key in expired:
        del _cache[key]


def invalidate_user_analytics_cache(user_id: uuid.UUID) -> None:
    """Drop all cached analytics entries for a user so the next request recomputes.

    Call this after any write that can change qualifying-application counts or
    response state (status/applied_at/stage-event changes) — otherwise the 10-minute
    cache can mask a user crossing the unlock threshold or logging a new response.
    """
    stale = [key for key in _cache if key.startswith(f"{user_id}:")]
    for key in stale:
        del _cache[key]


def clear_analytics_cache() -> None:
    """Test helper."""
    _cache.clear()
