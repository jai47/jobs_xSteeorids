"""HTML/text templates for notification emails."""

from __future__ import annotations

import html
from datetime import date

from config import settings
from services.notifications.unsubscribe import build_unsubscribe_url


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def digest_email(
    user_name: str,
    digest_date: date,
    content_text: str,
    *,
    user_id: str,
) -> tuple[str, str, str]:
    """Return (subject, html, text)."""
    subject = f"AI Career Digest — {digest_date.isoformat()}"
    unsubscribe = build_unsubscribe_url(user_id, "digest")
    text = (
        f"Hi {_escape(user_name)},\n\n"
        f"{content_text}\n\n"
        f"Open dashboard: {settings.app_base_url}/digest\n\n"
        f"Unsubscribe from digest emails: {unsubscribe}\n"
    )
    body_html = "<pre style='font-family:monospace;white-space:pre-wrap'>"
    body_html += _escape(content_text)
    body_html += "</pre>"
    html_doc = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;color:#222">
<p>Hi {_escape(user_name)},</p>
{body_html}
<p><a href="{settings.app_base_url}/digest">Open dashboard</a></p>
<p style="font-size:12px;color:#666"><a href="{unsubscribe}">Unsubscribe from digest emails</a></p>
</body></html>"""
    return subject, html_doc, text


def follow_up_batch_email(
    user_name: str,
    items: list[dict],
    *,
    user_id: str,
) -> tuple[str, str, str]:
    """Batch follow-up reminder email. Each item: company, title, days, draft_body."""
    subject = f"Follow-up reminders ({len(items)})"
    unsubscribe = build_unsubscribe_url(user_id, "followup")
    lines: list[str] = [f"Hi {user_name},", "", "You have applications that may need a follow-up:", ""]
    html_parts = [f"<p>Hi {_escape(user_name)},</p><p>You have applications that may need a follow-up:</p>"]
    for item in items:
        header = f"• {item['company']} — {item['title']} (applied {item['days']} days ago)"
        lines.append(header)
        lines.append(item["draft_body"])
        lines.append("")
        html_parts.append(
            f"<h3>{_escape(item['company'])} — {_escape(item['title'])}</h3>"
            f"<p><em>Applied {item['days']} days ago</em></p>"
            f"<pre style='white-space:pre-wrap'>{_escape(item['draft_body'])}</pre>"
        )
    lines.append(f"Open tracker: {settings.app_base_url}/tracker")
    lines.append(f"Unsubscribe: {unsubscribe}")
    text = "\n".join(lines)
    html_parts.append(f'<p><a href="{settings.app_base_url}/tracker">Open tracker</a></p>')
    html_parts.append(f'<p style="font-size:12px"><a href="{unsubscribe}">Unsubscribe from follow-up emails</a></p>')
    return subject, "\n".join(html_parts), text
