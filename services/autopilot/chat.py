"""Visual + text Autopilot chat coach grounded in Today Queue."""

from __future__ import annotations

from sqlalchemy.orm import Session

from api.deps import LLMError
from api.schemas.autopilot import (
    ChatHistoryMessage,
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    ChatVisual,
    ChatVisualChecklistItem,
    ChatVisualJob,
    ChatVisualProgress,
    ChatVisualStat,
    SuggestedAction,
)
from db.models import User
from llm.autopilot_chat import generate_chat_reply
from services.autopilot.coach_tours import match_tour, tour_action_label
from services.autopilot.state import get_user_autopilot, patch_user_autopilot
from services.autopilot.today import build_today_queue
from services.llm_generation_guard import enforce_daily_generation_guard

ACTION_PATHS = {
    "open_today": "/today",
    "open_tracker": "/tracker",
    "open_opportunities": "/opportunities",
    "open_networks": "/networks",
    "open_analytics": "/analytics",
    "open_coach": "/coach",
    "ensure_packet": "/tracker",
    "message_pack": "/tracker",
    "interview_pack": "/tracker",
    "follow_up": "/tracker",
}


def _build_visuals(queue, *, message: str) -> list[ChatVisual]:
    """Deterministic visual cards from live queue — always available without LLM."""
    visuals: list[ChatVisual] = []
    _ = message  # reserved for future intent-based filtering

    visuals.append(
        ChatVisual(
            type="stat_row",
            title="Your search at a glance",
            stats=[
                ChatVisualStat(
                    label="Jobs to act on",
                    value=str(len(queue.opportunities)),
                    tone="accent" if queue.opportunities else "neutral",
                ),
                ChatVisualStat(
                    label="Follow-ups",
                    value=str(len(queue.follow_ups)),
                    tone="warn" if queue.follow_ups else "ok",
                ),
                ChatVisualStat(
                    label="Packet gaps",
                    value=str(len(queue.packet_gaps)),
                    tone="warn" if queue.packet_gaps else "ok",
                ),
                ChatVisualStat(
                    label="Interview nudges",
                    value=str(len(queue.interview_nudges)),
                    tone="accent" if queue.interview_nudges else "neutral",
                ),
            ],
        )
    )

    done = 0
    total = 4
    if not queue.follow_ups:
        done += 1
    if not queue.packet_gaps:
        done += 1
    if queue.opportunities:
        done += 1
    if not queue.interview_nudges or len(queue.interview_nudges) == 0:
        done += 1
    # Always show a readiness bar
    readiness = int(round((done / total) * 100)) if total else 0
    if queue.follow_ups:
        readiness = max(10, readiness - 20)
    visuals.append(
        ChatVisual(
            type="progress",
            title="Today readiness",
            progress=ChatVisualProgress(label="Cleared vs remaining", value=max(5, readiness), max=100),
        )
    )

    if queue.opportunities:
        visuals.append(
            ChatVisual(
                type="job_list",
                title="Top matches to review",
                jobs=[
                    ChatVisualJob(
                        title=o.title,
                        company=o.company,
                        score=o.overall_score,
                        opportunity_id=o.opportunity_id,
                        url=o.url,
                    )
                    for o in queue.opportunities[:4]
                ],
            )
        )

    checklist_items: list[ChatVisualChecklistItem] = []
    if queue.follow_ups:
        checklist_items.append(
            ChatVisualChecklistItem(
                label=f"Clear follow-up: {queue.follow_ups[0].label}",
                done=False,
                path="/tracker",
            )
        )
    else:
        checklist_items.append(
            ChatVisualChecklistItem(label="Follow-ups clear", done=True, path="/tracker")
        )
    if queue.packet_gaps:
        checklist_items.append(
            ChatVisualChecklistItem(
                label=f"Finish Apply Packet: {queue.packet_gaps[0].company}",
                done=False,
                path="/tracker",
            )
        )
    else:
        checklist_items.append(
            ChatVisualChecklistItem(label="Apply packets ready", done=True, path="/tracker")
        )
    if queue.opportunities:
        checklist_items.append(
            ChatVisualChecklistItem(
                label=f"Review {queue.opportunities[0].title} @ {queue.opportunities[0].company}",
                done=False,
                path="/opportunities",
            )
        )
    visuals.append(
        ChatVisual(type="checklist", title="Suggested focus", checklist=checklist_items[:4])
    )

    visuals.append(
        ChatVisual(
            type="quick_replies",
            title="Ask me",
            quick_replies=[
                "What should I do next?",
                "Show my top jobs",
                "Help with follow-ups",
                "How is my search going?",
            ],
        )
    )

    if queue.follow_ups:
        visuals.append(
            ChatVisual(
                type="tip",
                title="Priority",
                body="Overdue follow-ups first — a short note beats a perfect one you never send.",
            )
        )
    elif queue.packet_gaps:
        visuals.append(
            ChatVisual(
                type="tip",
                title="Priority",
                body="Finish Apply Packets so you can submit with resume + letter + LinkedIn note ready.",
            )
        )

    visuals.append(
        ChatVisual(type="route_cta", label="Open Today queue", path="/today")
    )
    return visuals[:8]


def _enrich_actions(actions: list[SuggestedAction]) -> list[SuggestedAction]:
    out: list[SuggestedAction] = []
    for a in actions:
        path = a.path or ACTION_PATHS.get(a.action)
        out.append(
            SuggestedAction(
                action=a.action,
                label=a.label,
                application_id=a.application_id,
                path=path,
            )
        )
    return out


def get_chat_history(user: User) -> ChatHistoryResponse:
    raw = list(get_user_autopilot(user).get("chat_memory") or [])
    messages: list[ChatHistoryMessage] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        visuals = []
        for v in item.get("visuals") or []:
            if isinstance(v, dict):
                try:
                    visuals.append(ChatVisual.model_validate(v))
                except Exception:
                    continue
        actions = []
        for a in item.get("suggested_actions") or []:
            if isinstance(a, dict) and a.get("action"):
                try:
                    actions.append(SuggestedAction.model_validate(a))
                except Exception:
                    continue
        messages.append(
            ChatHistoryMessage(
                role=role,
                content=str(item.get("content") or ""),
                visuals=visuals,
                suggested_actions=actions,
            )
        )
    return ChatHistoryResponse(messages=messages)


def clear_chat_history(user: User) -> ChatHistoryResponse:
    patch_user_autopilot(user, chat_memory=[])
    return ChatHistoryResponse(messages=[])


def run_chat(session: Session, user: User, payload: ChatRequest) -> ChatResponse:
    enforce_daily_generation_guard(session, user.id)
    queue = build_today_queue(session, user)
    visuals = _build_visuals(queue, message=payload.message)
    context = {
        "opportunities": [o.model_dump() for o in queue.opportunities[:5]],
        "follow_ups": [f.model_dump(mode="json") for f in queue.follow_ups[:5]],
        "packet_gaps": [p.model_dump() for p in queue.packet_gaps[:5]],
        "interview_nudges": [i.model_dump() for i in queue.interview_nudges[:5]],
        "preferred_roles": list(user.preferred_roles or []),
        "skills": list(user.parsed_skills or [])[:15],
    }
    memory = list(get_user_autopilot(user).get("chat_memory") or [])
    recent = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in memory[-6:]
        if isinstance(m, dict)
    ]

    mood: str = "neutral"
    raw: dict = {}
    try:
        raw = generate_chat_reply(
            message=payload.message,
            candidate_name=user.name,
            context=context,
            recent_messages=recent,
            user_id=user.id,
            session=session,
        )
        reply = str(raw.get("reply") or "").strip() or (
            "Focus on your Today Queue: clear follow-ups, then finish Apply Packets."
        )
        mood = str(raw.get("mood") or "neutral")
        if mood not in {"neutral", "encouraging", "urgent", "celebratory"}:
            mood = "neutral"
        actions = [
            SuggestedAction(
                action=str(a.get("action") or ""),
                label=str(a.get("label") or a.get("action") or "Action"),
                application_id=a.get("application_id"),
                path=a.get("path"),
            )
            for a in (raw.get("suggested_actions") or [])
            if isinstance(a, dict) and a.get("action")
        ]
    except (LLMError, Exception):
        reply = (
            f"You have {len(queue.opportunities)} high-score jobs, "
            f"{len(queue.follow_ups)} follow-ups, and {len(queue.packet_gaps)} packet gaps. "
            "Start with overdue follow-ups, then ensure Apply Packets for approved roles."
        )
        actions = []
        mood = "urgent" if queue.follow_ups else "encouraging"
        if queue.packet_gaps:
            actions.append(
                SuggestedAction(
                    action="ensure_packet",
                    label=f"Ensure packet: {queue.packet_gaps[0].company}",
                    application_id=queue.packet_gaps[0].application_id,
                    path="/tracker",
                )
            )
        if queue.follow_ups:
            actions.append(
                SuggestedAction(
                    action="follow_up",
                    label=f"Follow up: {queue.follow_ups[0].label}",
                    application_id=(
                        queue.follow_ups[0].id
                        if queue.follow_ups[0].kind == "application"
                        else None
                    ),
                    path="/tracker",
                )
            )

    actions = _enrich_actions(actions)

    llm_tid = str(raw.get("tour_id") or "").strip() or None
    tour_id, tour_steps = match_tour(payload.message, tour_id=llm_tid)

    if tour_steps:
        actions.insert(
            0,
            SuggestedAction(
                action=f"start_tour:{tour_id}",
                label=tour_action_label(tour_id or "site_tour"),
                application_id=None,
                path=tour_steps[0].path,
            ),
        )
        if "tour" not in reply.lower() and "guide" not in reply.lower() and "walk" not in reply.lower():
            reply = (
                f"{reply.rstrip()} I’ll walk you through it on the page — tap "
                f"“{tour_action_label(tour_id or 'site_tour')}”."
            )
    else:
        # Offer optional full tour (steps fetched via GET /coach-tours/site_tour)
        tour_id, tour_steps = None, []
        actions.append(
            SuggestedAction(
                action="start_tour:site_tour",
                label="Start site tour",
                application_id=None,
                path="/today",
            )
        )

    if not any(a.action.startswith("open_") or a.path for a in actions):
        actions.append(
            SuggestedAction(action="open_today", label="Open Today", path="/today")
        )

    # Dedupe actions by label
    seen: set[str] = set()
    deduped: list[SuggestedAction] = []
    for a in actions:
        key = a.label.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
    actions = deduped

    memory.append({"role": "user", "content": payload.message[:500]})
    memory.append(
        {
            "role": "assistant",
            "content": reply[:800],
            "visuals": [v.model_dump() for v in visuals[:4]],
            "suggested_actions": [a.model_dump() for a in actions[:6]],
            "tour_id": tour_id if tour_steps else None,
            "tour": [s.model_dump() for s in tour_steps[:12]],
        }
    )
    patch_user_autopilot(user, chat_memory=memory[-16:])
    session.flush()
    return ChatResponse(
        reply=reply,
        suggested_actions=actions[:6],
        visuals=visuals,
        mood=mood,  # type: ignore[arg-type]
        tour_id=tour_id if tour_steps else None,
        tour=tour_steps,
    )
