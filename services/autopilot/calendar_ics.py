"""Build a calendar .ics from Today Queue follow-ups and apply blocks."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from db.models import User
from services.autopilot.today import build_today_queue


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_calendar_ics(session: Session, user: User) -> str:
    queue = build_today_queue(session, user)
    now = datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AI Career Copilot//Autopilot//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    # Two 45-minute apply blocks tomorrow and next day at 10:00 UTC
    for offset in (1, 2):
        day = (now + timedelta(days=offset)).date()
        start = datetime(day.year, day.month, day.day, 10, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=45)
        uid = f"apply-block-{day.isoformat()}-{user.id}@career-copilot"
        n = len(queue.opportunities)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{_fmt(now)}",
                f"DTSTART:{_fmt(start)}",
                f"DTEND:{_fmt(end)}",
                f"SUMMARY:{_escape(f'Career Copilot apply block ({n} queued)')}",
                f"DESCRIPTION:{_escape('Review Today Queue and complete Apply Packets.')}",
                "END:VEVENT",
            ]
        )

    for item in queue.follow_ups:
        due = item.due or date.today()
        start = datetime(due.year, due.month, due.day, 9, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=30)
        uid = f"followup-{item.kind}-{item.id}@career-copilot"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{_fmt(now)}",
                f"DTSTART:{_fmt(start)}",
                f"DTEND:{_fmt(end)}",
                f"SUMMARY:{_escape(f'Follow up: {item.label}')}",
                f"DESCRIPTION:{_escape(item.detail or 'Follow up from Career Copilot Autopilot')}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
