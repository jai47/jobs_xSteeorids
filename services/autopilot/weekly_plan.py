"""Weekly skill plan from skill-gap reports."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.autopilot import WeeklyPlanAction, WeeklyPlanResponse
from db.models import User
from llm.weekly_plan import generate_weekly_skill_plan
from services.autopilot.state import get_user_autopilot, patch_user_autopilot
from services.llm_generation_guard import enforce_daily_generation_guard
from services.skill_gap_reports import get_skill_gap_reports


def get_saved_weekly_plan(user: User) -> WeeklyPlanResponse | None:
    raw = get_user_autopilot(user).get("weekly_skill_plan")
    if not isinstance(raw, dict) or not raw:
        return None
    return _to_response(raw)


def _to_response(payload: dict) -> WeeklyPlanResponse:
    analyzed_at = None
    if isinstance(payload.get("generated_at"), str):
        try:
            analyzed_at = datetime.fromisoformat(payload["generated_at"].replace("Z", "+00:00"))
        except ValueError:
            pass
    actions = [
        WeeklyPlanAction(
            action=str(a.get("action") or ""),
            why=str(a.get("why") or ""),
            effort=a.get("effort") if a.get("effort") in ("low", "medium", "high") else "medium",
        )
        for a in (payload.get("actions") or [])
        if isinstance(a, dict) and a.get("action")
    ]
    return WeeklyPlanResponse(
        period_label=payload.get("period_label"),
        actions=actions,
        focus_skills=[str(s) for s in (payload.get("focus_skills") or []) if str(s).strip()],
        generated_at=analyzed_at,
    )


def generate_and_store_weekly_plan(session: Session, user: User) -> WeeklyPlanResponse:
    reports = get_skill_gap_reports(session, user)
    weekly = reports.get("weekly") or reports.get("monthly")
    if not weekly or not weekly.get("top_missing_skills"):
        # Deterministic fallback without LLM
        payload = {
            "period_label": "no skill-gap report yet",
            "actions": [
                {
                    "action": "Run the nightly pipeline and open Skill Gap in Settings after it completes.",
                    "why": "Weekly plan is driven by missing skills across scored jobs.",
                    "effort": "low",
                }
            ],
            "focus_skills": [],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        patch_user_autopilot(user, weekly_skill_plan=payload)
        session.flush()
        return _to_response(payload)

    skills = weekly.get("top_missing_skills") or []
    focus = [
        str(s.get("skill") or s) if isinstance(s, dict) else str(s)
        for s in skills[:8]
    ]
    period_label = f"{weekly.get('period_type') or 'weekly'} {weekly.get('period_start')}–{weekly.get('period_end')}"

    enforce_daily_generation_guard(session, user.id)
    try:
        raw = generate_weekly_skill_plan(
            missing_skills=skills[:10],
            candidate_name=user.name,
            preferred_roles=list(user.preferred_roles or []),
            user_id=user.id,
            session=session,
        )
        actions = raw.get("actions") or []
    except (LLMError, Exception):
        actions = [
            {
                "action": f"Add a quantified bullet showing {focus[0]} on your master resume"
                if focus
                else "Tighten your resume summary for target roles",
                "why": "Improves ATS and recruiter scan match",
                "effort": "medium",
            },
            {
                "action": "Practice one STAR story covering your top missing theme",
                "why": "Interview conversion once you get calls",
                "effort": "medium",
            },
            {
                "action": "Approve 3 high-score jobs and complete Apply Packets today",
                "why": "Volume + quality of tailored apps",
                "effort": "high",
            },
        ]

    payload = {
        "period_label": period_label,
        "actions": actions,
        "focus_skills": focus,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    patch_user_autopilot(user, weekly_skill_plan=payload)
    session.flush()
    return _to_response(payload)
