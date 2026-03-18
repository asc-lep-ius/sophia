"""Shared HTTP utilities — session factory, retry logic, and SSRF protection."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlparse

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

_ALLOWED_REDIRECT_DOMAINS: frozenset[str] = frozenset(
    {
        "tuwel.tuwien.ac.at",
        "tiss.tuwien.ac.at",
        "tuwien.ac.at",
        "iu.zid.tuwien.ac.at",
        "opencast.lecturetubes.at",
        "lecturetube.tuwien.ac.at",
    }
)

_PRIVATE_NETWORKS = (
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fc00::/7"),
)

_REDIRECT_STATUSES = frozenset({301, 302, 307, 308})


def _is_private_ip(host: str) -> bool:
    """Return True if *host* is a private/loopback/link-local IP address."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETWORKS)


def _is_allowed_redirect(url: str) -> bool:
    """Return True if *url* targets an allowed domain and is not a private IP."""
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if _is_private_ip(host):
        return False

    return any(
        host == domain or host.endswith(f".{domain}") for domain in _ALLOWED_REDIRECT_DOMAINS
    )


async def _validate_redirect(response: httpx.Response) -> None:
    """Event hook: block redirects to non-whitelisted domains (SSRF protection)."""
    if response.status_code not in _REDIRECT_STATUSES:
        return

    location = response.headers.get("location")
    if not location:
        return

    if not _is_allowed_redirect(location):
        raise httpx.HTTPStatusError(
            f"SSRF protection: redirect to {location!r} blocked",
            request=response.request,
            response=response,
        )


@asynccontextmanager
async def http_session(timeout: float = 30.0) -> AsyncIterator[httpx.AsyncClient]:
    """Create a shared httpx async client with sensible defaults."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10),
        event_hooks={"response": [_validate_redirect]},
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
