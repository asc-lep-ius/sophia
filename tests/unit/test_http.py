"""Tests for HTTP utilities — SSRF protection, retry logic, and session factory."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from sophia.infra.http import (
    _is_allowed_redirect,
    _is_private_ip,
    _should_retry_status,
    _validate_redirect,
    fetch_with_retry,
    http_session,
)

# ── _is_private_ip ────────────────────────────────────────────────────────


class TestIsPrivateIp:
    def test_localhost(self) -> None:
        assert _is_private_ip("127.0.0.1") is True

    def test_private_10(self) -> None:
        assert _is_private_ip("10.0.0.1") is True

    def test_private_172(self) -> None:
        assert _is_private_ip("172.16.0.1") is True

    def test_private_192(self) -> None:
        assert _is_private_ip("192.168.1.1") is True

    def test_ipv6_loopback(self) -> None:
        assert _is_private_ip("::1") is True

    def test_public_ip(self) -> None:
        assert _is_private_ip("8.8.8.8") is False

    def test_hostname_returns_false(self) -> None:
        assert _is_private_ip("example.com") is False


# ── _is_allowed_redirect ──────────────────────────────────────────────────


class TestIsAllowedRedirect:
    def test_allowed_tuwel(self) -> None:
        assert _is_allowed_redirect("https://tuwel.tuwien.ac.at/course") is True

    def test_allowed_tiss(self) -> None:
        assert _is_allowed_redirect("https://tiss.tuwien.ac.at/api") is True

    def test_subdomain_allowed(self) -> None:
        assert _is_allowed_redirect("https://foo.tuwien.ac.at/bar") is True

    def test_blocked_domain(self) -> None:
        assert _is_allowed_redirect("https://evil.example.com/steal") is False

    def test_private_ip_blocked(self) -> None:
        assert _is_allowed_redirect("http://127.0.0.1/admin") is False


# ── _should_retry_status ──────────────────────────────────────────────────


class TestShouldRetryStatus:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (429, True),
            (500, True),
            (502, True),
            (503, True),
            (200, False),
            (301, False),
            (404, False),
            (499, False),
        ],
    )
    def test_retry_decision(self, status: int, expected: bool) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = status
        assert _should_retry_status(response) is expected


# ── _validate_redirect ────────────────────────────────────────────────────


class TestValidateRedirect:
    @pytest.mark.asyncio
    async def test_non_redirect_is_noop(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        await _validate_redirect(response)  # should not raise

    @pytest.mark.asyncio
    async def test_redirect_to_allowed_domain_passes(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = 302
        response.headers = {"location": "https://tuwel.tuwien.ac.at/login"}
        await _validate_redirect(response)  # should not raise

    @pytest.mark.asyncio
    async def test_redirect_to_blocked_domain_raises(self) -> None:
        request = MagicMock(spec=httpx.Request)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 302
        response.headers = {"location": "https://evil.example.com/phish"}
        response.request = request
        with pytest.raises(httpx.HTTPStatusError, match="SSRF"):
            await _validate_redirect(response)

    @pytest.mark.asyncio
    async def test_redirect_without_location_is_noop(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = 301
        response.headers = {}
        await _validate_redirect(response)  # should not raise

    @pytest.mark.asyncio
    async def test_redirect_to_private_ip_raises(self) -> None:
        request = MagicMock(spec=httpx.Request)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 307
        response.headers = {"location": "http://127.0.0.1/admin"}
        response.request = request
        with pytest.raises(httpx.HTTPStatusError, match="SSRF"):
            await _validate_redirect(response)


# ── http_session ───────────────────────────────────────────────────────────


class TestHttpSession:
    @pytest.mark.asyncio
    async def test_yields_async_client(self) -> None:
        async with http_session() as client:
            assert isinstance(client, httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_custom_timeout(self) -> None:
        async with http_session(timeout=5.0) as client:
            assert client.timeout.connect == 5.0


# ── fetch_with_retry ──────────────────────────────────────────────────────


class TestFetchWithRetry:
    @pytest.mark.asyncio
    async def test_success_returns_response(self) -> None:
        async with http_session() as _client:
            # Use httpx's mock transport
            transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
            mock_client = httpx.AsyncClient(transport=transport)
            response = await fetch_with_retry(mock_client, "https://example.com/api")
            assert response.status_code == 200
            await mock_client.aclose()

    @pytest.mark.asyncio
    async def test_raises_on_client_error(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(404, text="not found"))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_with_retry(client, "https://example.com/missing")

    @pytest.mark.asyncio
    async def test_retries_on_429_with_retry_after(self) -> None:
        """429 with Retry-After header triggers sleep and retry."""
        from unittest.mock import AsyncMock, patch

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, text="ok")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with patch("sophia.infra.http.asyncio.sleep", new_callable=AsyncMock):
                # Override tenacity wait to avoid actual delays
                from tenacity import stop_after_attempt, wait_none

                fast_retry = fetch_with_retry.retry_with(  # type: ignore[attr-defined]
                    wait=wait_none(), stop=stop_after_attempt(3)
                )
                response = await fast_retry(client, "https://example.com/api")

        assert response.status_code == 200
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_server_error(self) -> None:
        """5xx errors are retried."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, text="error")
            return httpx.Response(200, text="ok")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            from tenacity import stop_after_attempt, wait_none

            fast_retry = fetch_with_retry.retry_with(  # type: ignore[attr-defined]
                wait=wait_none(), stop=stop_after_attempt(3)
            )
            response = await fast_retry(client, "https://example.com/api")

        assert response.status_code == 200
        assert call_count == 2
