"""Shared async HTTP client with retry and backoff."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

HTTP_TIMEOUT = httpx.Timeout(connect=15.0, read=45.0, write=15.0, pool=10.0)
MAX_RETRIES = 3
BACKOFF_BASE = 1.5


class HTTPFetchError(Exception):
    """Raised when an HTTP request fails after retries."""


async def fetch_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """Fetch JSON with retries for transient failures and rate limits."""
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.request(method, url, json=json_body, headers=headers)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else BACKOFF_BASE * (2**attempt)
                log.warning("Rate limited on %s; sleeping %.1fs", url, delay)
                await asyncio.sleep(delay)
                continue
            if response.status_code >= 500:
                delay = BACKOFF_BASE * (2**attempt)
                log.warning("Server error %s on %s; retrying in %.1fs", response.status_code, url, delay)
                await asyncio.sleep(delay)
                continue
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except httpx.ReadTimeout as exc:
            if attempt == 0:
                log.warning("Read timeout on %s; retrying once", url)
                await asyncio.sleep(BACKOFF_BASE)
                last_error = exc
                continue
            raise HTTPFetchError(f"Read timeout on {url}") from exc
        except httpx.ConnectTimeout as exc:
            delay = BACKOFF_BASE * (2**attempt)
            log.warning("Connect timeout on %s; retrying in %.1fs", url, delay)
            await asyncio.sleep(delay)
            last_error = exc
        except httpx.HTTPStatusError as exc:
            if 400 <= exc.response.status_code < 500 and exc.response.status_code != 429:
                raise HTTPFetchError(
                    f"HTTP {exc.response.status_code} on {url}: {exc.response.text[:200]}"
                ) from exc
            last_error = exc
            delay = BACKOFF_BASE * (2**attempt)
            await asyncio.sleep(delay)
        except httpx.HTTPError as exc:
            last_error = exc
            delay = BACKOFF_BASE * (2**attempt)
            await asyncio.sleep(delay)

    raise HTTPFetchError(f"Failed to fetch {url}") from last_error


def get_async_client() -> httpx.AsyncClient:
    """Return a configured async HTTP client."""
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)
