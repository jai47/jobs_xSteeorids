"""Targeting patterns from rejects, skips, and stalled applications."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.schemas.autopilot import (
    PatternInsight,
    PatternsResponse,
    PatternStat,
)
from db.models import Application, Job, ScoredOpportunity, User
from llm.patterns_summary import generate_patterns_summary
from services.autopilot.state import get_user_autopilot, patch_user_autopilot
from services.llm_generation_guard import enforce_daily_generation_guard


def _top_counts(counter: Counter[str], *, limit: int = 8) -> list[PatternStat]:
    return [
        PatternStat(key=k, count=c, label=k.replace("_", " "))
        for k, c in counter.most_common(limit)
        if k
    ]


def build_patterns(
    session: Session,
    user: User,
    *,
    refresh_summary: bool = False,
) -> PatternsResponse:
    opps = (
        session.query(ScoredOpportunity, Job)
        .join(Job, ScoredOpportunity.job_id == Job.id)
        .filter(ScoredOpportunity.user_id == user.id)
        .all()
    )
    apps = (
        session.query(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .filter(Application.user_id == user.id)
        .all()
    )

    reject_reasons: Counter[str] = Counter()
    rejected_companies: Counter[str] = Counter()
    rejected_archetypes: Counter[str] = Counter()
    skipped_companies: Counter[str] = Counter()
    high_score_rejects: list[str] = []
    ghosted: list[str] = []

    for opp, job in opps:
        fb = (opp.user_feedback or "").lower()
        if fb == "rejected":
            reject_reasons[opp.reject_reason or "other"] += 1
            rejected_companies[job.company] += 1
            if job.archetype:
                rejected_archetypes[job.archetype] += 1
            if (opp.overall_score or 0) >= 70:
                high_score_rejects.append(f"{job.title} @ {job.company} ({opp.overall_score})")
        elif fb == "skipped":
            skipped_companies[job.company] += 1

    applied_stale = 0
    for app, job in apps:
        status = (app.status or "").lower()
        if status == "applied" and app.follow_up_due:
            from datetime import date

            if app.follow_up_due < date.today() and not app.followed_up_at:
                ghosted.append(f"{job.title} @ {job.company}")
                applied_stale += 1

    insights: list[PatternInsight] = []
    if reject_reasons:
        top_reason, n = reject_reasons.most_common(1)[0]
        insights.append(
            PatternInsight(
                kind="reject_reason",
                title=f"Most common reject reason: {top_reason}",
                detail=f"You rejected {n} roles primarily for '{top_reason}'. Consider tightening filters upstream.",
                severity="info",
            )
        )
    if high_score_rejects:
        insights.append(
            PatternInsight(
                kind="high_score_reject",
                title="High-score roles you still rejected",
                detail="; ".join(high_score_rejects[:5]),
                severity="warn",
            )
        )
    if rejected_archetypes:
        arch, n = rejected_archetypes.most_common(1)[0]
        insights.append(
            PatternInsight(
                kind="archetype",
                title=f"Frequent archetype rejects: {arch.replace('_', ' ')}",
                detail=f"{n} rejected roles in this archetype — check if preferences or resume positioning mismatch.",
                severity="info",
            )
        )
    if applied_stale:
        insights.append(
            PatternInsight(
                kind="ghost_risk",
                title=f"{applied_stale} applied roles need follow-up",
                detail="; ".join(ghosted[:5]) or "Clear overdue follow-ups from Today.",
                severity="warn",
            )
        )
    if not insights:
        insights.append(
            PatternInsight(
                kind="empty",
                title="Not enough outcome data yet",
                detail="Reject, skip, and apply more roles to surface targeting patterns.",
                severity="info",
            )
        )

    summary = None
    cache = get_user_autopilot(user).get("patterns_summary")
    if isinstance(cache, dict) and cache.get("text") and not refresh_summary:
        summary = str(cache["text"])
    elif refresh_summary or not summary:
        # Optional LLM polish — fail soft
        try:
            enforce_daily_generation_guard(session, user.id)
            raw = generate_patterns_summary(
                insights=[i.model_dump() for i in insights],
                reject_reasons=dict(reject_reasons),
                rejected_companies=dict(rejected_companies.most_common(5)),
                user_id=user.id,
                session=session,
            )
            summary = str(raw.get("summary") or "").strip() or None
            if summary:
                patch_user_autopilot(
                    user,
                    patterns_summary={
                        "text": summary,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        except Exception:
            summary = None

    return PatternsResponse(
        total_opportunities=len(opps),
        total_applications=len(apps),
        reject_reasons=_top_counts(reject_reasons),
        rejected_companies=_top_counts(rejected_companies),
        rejected_archetypes=_top_counts(rejected_archetypes),
        skipped_companies=_top_counts(skipped_companies),
        insights=insights,
        summary=summary,
        generated_at=datetime.now(timezone.utc),
    )
