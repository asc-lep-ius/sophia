"""Request context middleware tests."""

from __future__ import annotations

import asyncio

import anyio
import httpx
from fastapi.testclient import TestClient

from sophia.api import create_api_app
from sophia.api.context import get_request_context, require_request_context


def test_request_context_is_set_and_cleared_per_request() -> None:
    api_app = create_api_app()

    @api_app.get("/api/_context")
    async def inspect_context() -> dict[str, str]:
        context = require_request_context()
        return {"request_id": context.request_id}

    client = TestClient(api_app)

    response = client.get("/api/_context", headers={"X-Request-ID": "req-one"})

    assert response.status_code == 200
    assert response.json() == {"request_id": "req-one"}
    assert response.headers["x-request-id"] == "req-one"
    assert get_request_context() is None


async def test_concurrent_request_contexts_do_not_bleed() -> None:
    api_app = create_api_app()

    @api_app.get("/api/_context/echo")
    async def echo_context() -> dict[str, str]:
        first_context = require_request_context()
        await anyio.sleep(0.01)
        second_context = require_request_context()
        return {
            "first_request_id": first_context.request_id,
            "second_request_id": second_context.request_id,
        }

    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response, second_response = await asyncio.gather(
            client.get("/api/_context/echo", headers={"X-Request-ID": "req-a"}),
            client.get("/api/_context/echo", headers={"X-Request-ID": "req-b"}),
        )

    assert first_response.json() == {
        "first_request_id": "req-a",
        "second_request_id": "req-a",
    }
    assert second_response.json() == {
        "first_request_id": "req-b",
        "second_request_id": "req-b",
    }
    assert get_request_context() is None
