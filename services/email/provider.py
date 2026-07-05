"""Email transport adapters (Console + Resend)."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from config import settings

log = logging.getLogger(__name__)


class EmailProvider(Protocol):
    def send(self, to: str, subject: str, html: str, text: str) -> None: ...


class ConsoleEmailProvider:
    """Dev default — logs email content, sends nothing."""

    def send(self, to: str, subject: str, html: str, text: str) -> None:
        log.info(
            "ConsoleEmailProvider: to=%s subject=%r text_len=%d html_len=%d",
            to,
            subject,
            len(text),
            len(html),
        )


class ResendEmailProvider:
    """Production email via Resend API."""

    def __init__(self, api_key: str, from_address: str) -> None:
        self.api_key = api_key
        self.from_address = from_address

    def send(self, to: str, subject: str, html: str, text: str) -> None:
        if not self.api_key:
            raise RuntimeError("RESEND_API_KEY is not configured")
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": self.from_address,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Resend API error {response.status_code}: {response.text}")


def get_email_provider() -> EmailProvider:
    provider = (settings.email_provider or "console").lower()
    if provider == "resend":
        return ResendEmailProvider(settings.resend_api_key, settings.email_from_address)
    return ConsoleEmailProvider()
