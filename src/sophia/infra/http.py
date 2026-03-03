"""Shared HTTP utilities — session factory and retry logic."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


@asynccontextmanager
async def http_session(timeout: float = 30.0) -> AsyncIterator[httpx.AsyncClient]:
    """Create a shared httpx async client with sensible defaults."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10),
    ) as client:
        yield client


def _should_retry_status(response: httpx.Response) -> bool:
    """Retry on 429 (rate limited) and 5xx (server errors)."""
    if response.status_code == 429:
        return True
    return response.status_code >= 500


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=(
        retry_if_exception_type((httpx.TransportError, httpx.TimeoutException))
        | retry_if_exception(
            lambda e: isinstance(e, httpx.HTTPStatusError) and _should_retry_status(e.response)
        )
    ),
    before_sleep=None,
)
async def fetch_with_retry(client: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
    """HTTP GET with exponential backoff.

    Retries on transport errors, timeouts, 429 (rate limited), and 5xx.
    Respects Retry-After header when present.
    """
    response = await client.get(url, **kwargs)  # type: ignore[arg-type]
    if _should_retry_status(response):
        if retry_after := response.headers.get("Retry-After"):
            with contextlib.suppress(ValueError):
                await asyncio.sleep(float(retry_after))
        response.raise_for_status()
    response.raise_for_status()
    return response
