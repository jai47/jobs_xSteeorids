"""Short Autopilot chat coach grounded in Today Queue."""

from __future__ import annotations

from sqlalchemy.orm import Session

from api.deps import LLMError
from api.schemas.autopilot import ChatRequest, ChatResponse, SuggestedAction
from db.models import User
from llm.autopilot_chat import generate_chat_reply
from services.autopilot.state import get_user_autopilot, patch_user_autopilot
from services.autopilot.today import build_today_queue
from services.llm_generation_guard import enforce_daily_generation_guard


def run_chat(session: Session, user: User, payload: ChatRequest) -> ChatResponse:
    enforce_daily_generation_guard(session, user.id)
    queue = build_today_queue(session, user)
    context = {
        "opportunities": [o.model_dump() for o in queue.opportunities[:5]],
        "follow_ups": [f.model_dump(mode="json") for f in queue.follow_ups[:5]],
        "packet_gaps": [p.model_dump() for p in queue.packet_gaps[:5]],
        "interview_nudges": [i.model_dump() for i in queue.interview_nudges[:5]],
        "preferred_roles": list(user.preferred_roles or []),
        "skills": list(user.parsed_skills or [])[:15],
    }
    try:
        raw = generate_chat_reply(
            message=payload.message,
            candidate_name=user.name,
            context=context,
            user_id=user.id,
            session=session,
        )
        reply = str(raw.get("reply") or "").strip() or (
            "Focus on your Today Queue: clear follow-ups, then finish Apply Packets."
        )
        actions = [
            SuggestedAction(
                action=str(a.get("action") or ""),
                label=str(a.get("label") or a.get("action") or "Action"),
                application_id=a.get("application_id"),
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
        if queue.packet_gaps:
            actions.append(
                SuggestedAction(
                    action="ensure_packet",
                    label=f"Ensure packet: {queue.packet_gaps[0].company}",
                    application_id=queue.packet_gaps[0].application_id,
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
                )
            )

    memory = list(get_user_autopilot(user).get("chat_memory") or [])
    memory.append({"role": "user", "content": payload.message[:500]})
    memory.append({"role": "assistant", "content": reply[:800]})
    patch_user_autopilot(user, chat_memory=memory[-8:])
    session.flush()
    return ChatResponse(reply=reply, suggested_actions=actions[:5])
