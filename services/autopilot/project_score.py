"""Score a portfolio project idea against target roles + build time."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.deps import LLMError
from api.schemas.autopilot import ProjectScoreRequest, ProjectScoreResponse
from db.models import User
from llm.project_score import generate_project_score
from services.llm_generation_guard import enforce_daily_generation_guard


def _heuristic(payload: ProjectScoreRequest, user: User) -> dict:
    roles = " ".join(user.preferred_roles or []).lower()
    text = f"{payload.title} {payload.description or ''}".lower()
    skills = [s.lower() for s in (user.parsed_skills or [])]
    skill_hits = sum(1 for s in skills if s and s in text)
    role_hit = any(token in text for token in roles.split() if len(token) > 3)
    hours = payload.estimated_hours or 30
    score = 55 + min(25, skill_hits * 8) + (10 if role_hit else 0)
    if hours > 100:
        score -= 15
    elif hours < 20:
        score += 5
    score = max(15, min(95, int(score)))
    return {
        "score": score,
        "verdict": "build" if score >= 65 else "maybe" if score >= 45 else "skip",
        "summary": (
            f"'{payload.title}' is a {'strong' if score >= 65 else 'moderate'} resume signal "
            f"for your target roles (~{hours}h)."
        ),
        "why": [
            f"Skill keyword hits in idea: {skill_hits}",
            "Touches preferred role language" if role_hit else "Weak role-title overlap",
        ],
        "scope_tips": [
            "Ship an MVP with one demo metric in under 2 weeks",
            "Write a README with problem → approach → result",
        ],
        "resume_bullets": [
            f"Built {payload.title}: [metric] using [stack]",
        ],
    }


def score_project(
    session: Session,
    user: User,
    payload: ProjectScoreRequest,
) -> ProjectScoreResponse:
    enforce_daily_generation_guard(session, user.id)
    try:
        raw = generate_project_score(
            title=payload.title,
            description=payload.description or "",
            estimated_hours=payload.estimated_hours,
            preferred_roles=list(user.preferred_roles or []),
            skills=list(user.parsed_skills or []),
            candidate_name=user.name,
            user_id=user.id,
            session=session,
        )
    except (LLMError, Exception):
        raw = _heuristic(payload, user)

    score = max(0, min(100, int(raw.get("score") or 50)))
    verdict = str(raw.get("verdict") or "maybe")
    if verdict not in {"build", "maybe", "skip"}:
        verdict = "build" if score >= 65 else "maybe" if score >= 45 else "skip"

    return ProjectScoreResponse(
        title=payload.title.strip(),
        score=score,
        verdict=verdict,  # type: ignore[arg-type]
        summary=str(raw.get("summary") or ""),
        why=[str(x) for x in (raw.get("why") or []) if str(x).strip()][:6],
        scope_tips=[str(x) for x in (raw.get("scope_tips") or []) if str(x).strip()][:6],
        resume_bullets=[str(x) for x in (raw.get("resume_bullets") or []) if str(x).strip()][:4],
        scored_at=datetime.now(timezone.utc),
    )
