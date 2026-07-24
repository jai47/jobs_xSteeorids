"""Score a course/cert against career direction + opportunity cost."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.deps import LLMError
from api.schemas.autopilot import TrainingScoreRequest, TrainingScoreResponse
from db.models import User
from llm.training_score import generate_training_score
from services.llm_generation_guard import enforce_daily_generation_guard


def _heuristic(payload: TrainingScoreRequest, user: User) -> dict:
    roles = [r.lower() for r in (user.preferred_roles or [])]
    title_l = payload.title.lower()
    desc_l = (payload.description or "").lower()
    overlap = any(r.split()[0] in title_l or r.split()[0] in desc_l for r in roles if r)
    hours = payload.cost_hours or 40
    score = 72 if overlap else 48
    if hours > 80:
        score -= 10
    if (payload.cost_money or 0) > 2000:
        score -= 8
    score = max(15, min(95, score))
    return {
        "score": score,
        "verdict": "worth_it" if score >= 65 else "maybe" if score >= 45 else "skip",
        "summary": (
            f"'{payload.title}' looks {'aligned' if overlap else 'loosely related'} to your "
            f"preferred roles. Estimated effort ~{hours}h."
        ),
        "why": [
            "Matches a preferred role keyword" if overlap else "Weak keyword overlap with preferred roles",
            f"Time cost ~{hours} hours",
        ],
        "opportunity_cost": [
            "Could instead ship a portfolio project tied to a target JD",
            "Could deepen one gap skill from your weekly plan",
        ],
        "better_alternatives": [
            "A small public project demonstrating the same skill",
            "A free official docs path / tutorial series",
        ],
    }


def score_training(
    session: Session,
    user: User,
    payload: TrainingScoreRequest,
) -> TrainingScoreResponse:
    enforce_daily_generation_guard(session, user.id)
    try:
        raw = generate_training_score(
            title=payload.title,
            description=payload.description or "",
            cost_hours=payload.cost_hours,
            cost_money=payload.cost_money,
            url=payload.url,
            preferred_roles=list(user.preferred_roles or []),
            skills=list(user.parsed_skills or []),
            candidate_name=user.name,
            user_id=user.id,
            session=session,
        )
    except (LLMError, Exception):
        raw = _heuristic(payload, user)

    score = int(raw.get("score") or 50)
    score = max(0, min(100, score))
    verdict = str(raw.get("verdict") or "maybe")
    if verdict not in {"worth_it", "maybe", "skip"}:
        verdict = "worth_it" if score >= 65 else "maybe" if score >= 45 else "skip"

    return TrainingScoreResponse(
        title=payload.title.strip(),
        score=score,
        verdict=verdict,  # type: ignore[arg-type]
        summary=str(raw.get("summary") or ""),
        why=[str(x) for x in (raw.get("why") or []) if str(x).strip()][:6],
        opportunity_cost=[str(x) for x in (raw.get("opportunity_cost") or []) if str(x).strip()][:6],
        better_alternatives=[str(x) for x in (raw.get("better_alternatives") or []) if str(x).strip()][:6],
        scored_at=datetime.now(timezone.utc),
    )
