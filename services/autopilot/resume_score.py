"""Score active master resume (Autopilot resume score dashboard)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.autopilot import ResumeScoreResponse, ResumeSectionScore
from db.models import User
from llm.resume_score import analyze_resume_score
from services.autopilot.state import get_user_autopilot, patch_user_autopilot
from services.llm_generation_guard import enforce_daily_generation_guard
from services.resume_tailoring import get_active_master_resume


def get_saved_resume_score(user: User) -> ResumeScoreResponse | None:
    raw = get_user_autopilot(user).get("resume_score")
    if not isinstance(raw, dict) or not raw:
        return None
    return _to_response(raw)


def _to_response(payload: dict) -> ResumeScoreResponse:
    analyzed_at = None
    if isinstance(payload.get("analyzed_at"), str):
        try:
            analyzed_at = datetime.fromisoformat(payload["analyzed_at"].replace("Z", "+00:00"))
        except ValueError:
            pass
    sections = [
        ResumeSectionScore(
            section=str(s.get("section") or "section"),
            score=int(s.get("score") or 0),
            feedback=str(s.get("feedback") or ""),
        )
        for s in (payload.get("sections") or [])
        if isinstance(s, dict)
    ]
    return ResumeScoreResponse(
        overall_score=int(payload.get("overall_score") or 0),
        summary=str(payload.get("summary") or ""),
        sections=sections,
        quick_wins=[str(w) for w in (payload.get("quick_wins") or []) if str(w).strip()][:8],
        analyzed_at=analyzed_at,
        master_resume_id=payload.get("master_resume_id"),
        persona_label=payload.get("persona_label"),
    )


def analyze_and_store_resume_score(session: Session, user: User) -> ResumeScoreResponse:
    enforce_daily_generation_guard(session, user.id)
    try:
        master = get_active_master_resume(session, user)
    except APIError:
        raise
    text = (master.raw_text or "").strip()
    if len(text) < 80:
        raise APIError(422, "Active master resume text is too short to score", "VALIDATION_ERROR")

    try:
        raw = analyze_resume_score(
            resume_text=text,
            candidate_name=user.name,
            target_roles=list(user.preferred_roles or []),
            user_id=user.id,
            session=session,
        )
    except LLMError as exc:
        raise APIError(502, str(exc), "LLM_ERROR") from exc
    except Exception as exc:
        raise APIError(502, f"Resume score failed: {exc}", "LLM_ERROR") from exc

    payload = {
        "overall_score": int(raw.get("overall_score") or 0),
        "summary": str(raw.get("summary") or "Score complete."),
        "sections": raw.get("sections") or [],
        "quick_wins": raw.get("quick_wins") or [],
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "master_resume_id": str(master.id),
        "persona_label": master.label,
    }
    patch_user_autopilot(user, resume_score=payload)
    session.flush()
    return _to_response(payload)
