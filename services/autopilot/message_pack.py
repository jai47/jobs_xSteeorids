"""Generate and cache LinkedIn/email message packs (sequences)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.autopilot import MessagePackItem, MessagePackResponse
from db.models import Application, Job, User
from llm.message_pack import generate_message_pack
from services.autopilot.state import get_app_autopilot, patch_app_autopilot
from services.llm_generation_guard import enforce_daily_generation_guard

MESSAGE_META = [
    ("connect", "LinkedIn connect note", "linkedin", 0, 300),
    ("follow_up_d7", "Follow-up day 7 (LinkedIn)", "linkedin", 7, 300),
    ("follow_up_d14", "Follow-up day 14 (email)", "email", 14, None),
    ("referral", "Referral ask", "linkedin", 0, 300),
    ("thank_you", "Thank-you after chat/interview", "email", 0, None),
    ("any_update", "Any update? nudge", "email", 10, None),
]


def get_stored_message_pack(application: Application) -> dict[str, Any] | None:
    cache = get_app_autopilot(application)
    pack = cache.get("message_pack")
    return pack if isinstance(pack, dict) else None


def _fallback_messages(user: User, job: Job) -> list[dict[str, Any]]:
    name = user.name.split()[0] if user.name else "there"
    company = job.company
    title = job.title
    return [
        {
            "key": "connect",
            "label": "LinkedIn connect note",
            "channel": "linkedin",
            "day_offset": 0,
            "max_chars": 300,
            "body": (
                f"Hi — I'm {name}, applying for {title} at {company}. "
                f"Would value any insight on the team or role. Thanks!"
            )[:300],
        },
        {
            "key": "follow_up_d7",
            "label": "Follow-up day 7 (LinkedIn)",
            "channel": "linkedin",
            "day_offset": 7,
            "max_chars": 300,
            "body": (
                f"Hi — following up on my {title} application at {company}. "
                f"Happy to share more detail if helpful."
            )[:300],
        },
        {
            "key": "follow_up_d14",
            "label": "Follow-up day 14 (email)",
            "channel": "email",
            "day_offset": 14,
            "max_chars": None,
            "body": (
                f"Subject: Following up — {title}\n\n"
                f"Dear {company} Hiring Team,\n\n"
                f"I wanted to follow up on my application for {title}. "
                f"I remain very interested and would welcome any update.\n\n"
                f"Best regards,\n{user.name}"
            ),
        },
        {
            "key": "referral",
            "label": "Referral ask",
            "channel": "linkedin",
            "day_offset": 0,
            "max_chars": 300,
            "body": (
                f"Hi — exploring the {title} role at {company}. "
                f"If you're open to it, I'd appreciate a referral or intro to the hiring team."
            )[:300],
        },
        {
            "key": "thank_you",
            "label": "Thank-you after chat/interview",
            "channel": "email",
            "day_offset": 0,
            "max_chars": None,
            "body": (
                f"Subject: Thank you — {title}\n\n"
                f"Thank you for the conversation about {title} at {company}. "
                f"I enjoyed learning more and remain enthusiastic about the opportunity.\n\n"
                f"Best,\n{user.name}"
            ),
        },
        {
            "key": "any_update",
            "label": "Any update? nudge",
            "channel": "email",
            "day_offset": 10,
            "max_chars": None,
            "body": (
                f"Subject: Checking in — {title}\n\n"
                f"Just checking whether there is any update on the {title} process. "
                f"Happy to provide anything else you need.\n\n"
                f"Thanks,\n{user.name}"
            ),
        },
    ]


def _to_response(application: Application, job: Job, pack: dict[str, Any]) -> MessagePackResponse:
    messages: list[MessagePackItem] = []
    for msg in pack.get("messages") or []:
        if not isinstance(msg, dict) or not msg.get("body"):
            continue
        messages.append(
            MessagePackItem(
                key=str(msg.get("key") or "note"),
                label=str(msg.get("label") or msg.get("key") or "Message"),
                channel=msg.get("channel") if msg.get("channel") in ("linkedin", "email") else "linkedin",
                body=str(msg["body"]),
                day_offset=int(msg.get("day_offset") or 0),
                max_chars=msg.get("max_chars"),
            )
        )
    generated_at = None
    raw_at = pack.get("generated_at")
    if isinstance(raw_at, str):
        try:
            generated_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        except ValueError:
            generated_at = None
    return MessagePackResponse(
        application_id=str(application.id),
        company=job.company,
        title=job.title,
        messages=messages,
        generated_at=generated_at,
    )


def get_message_pack(
    session: Session,
    user: User,
    application_id: uuid.UUID,
) -> MessagePackResponse | None:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")
    pack = get_stored_message_pack(application)
    if not pack:
        return None
    return _to_response(application, job, pack)


def generate_and_store_message_pack(
    session: Session,
    user: User,
    application_id: uuid.UUID,
    *,
    check_limits: bool = True,
) -> MessagePackResponse:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise APIError(404, "Application not found", "NOT_FOUND")
    job = session.get(Job, application.job_id)
    if job is None:
        raise APIError(404, "Job not found", "NOT_FOUND")

    if check_limits:
        enforce_daily_generation_guard(session, user.id)

    try:
        raw = generate_message_pack(
            company=job.company,
            job_title=job.title,
            job_description=job.description,
            candidate_name=user.name,
            skills=list(user.parsed_skills or []),
            user_id=user.id,
            session=session,
        )
        by_key = {
            str(m.get("key")): m
            for m in (raw.get("messages") or [])
            if isinstance(m, dict) and m.get("key")
        }
        messages = []
        for key, label, channel, day_offset, max_chars in MESSAGE_META:
            body = ""
            if key in by_key:
                body = str(by_key[key].get("body") or "").strip()
            if not body:
                # fill from fallback for this key
                for fb in _fallback_messages(user, job):
                    if fb["key"] == key:
                        body = fb["body"]
                        break
            if max_chars and len(body) > max_chars:
                body = body[: max_chars - 1].rstrip() + "…"
            messages.append(
                {
                    "key": key,
                    "label": label,
                    "channel": channel,
                    "day_offset": day_offset,
                    "max_chars": max_chars,
                    "body": body,
                }
            )
    except (LLMError, Exception):
        messages = _fallback_messages(user, job)

    pack = {
        "messages": messages,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    patch_app_autopilot(application, message_pack=pack)
    session.flush()
    return _to_response(application, job, pack)


def ensure_connect_note(
    session: Session,
    user: User,
    application: Application,
    job: Job,
    *,
    check_limits: bool = True,
) -> str | None:
    pack = get_stored_message_pack(application)
    if pack:
        for msg in pack.get("messages") or []:
            if isinstance(msg, dict) and msg.get("key") == "connect" and msg.get("body"):
                return str(msg["body"])
    result = generate_and_store_message_pack(
        session, user, application.id, check_limits=check_limits
    )
    for msg in result.messages:
        if msg.key == "connect":
            return msg.body
    return None
