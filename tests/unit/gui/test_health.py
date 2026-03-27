"""Tests for /health and /ready endpoints."""

from __future__ import annotations

from starlette.testclient import TestClient

from sophia.gui.middleware.health import (
    get_container,
    health,
    ready,
    reset_state,
    set_container,
    set_container_error,
)


def _build_test_app() -> TestClient:
    """Build a minimal Starlette app with health routes for testing."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    starlette_app = Starlette(
        routes=[
            Route("/health", health),
            Route("/ready", ready),
        ],
    )
    return TestClient(starlette_app)


class TestHealthEndpoint:
    def setup_method(self) -> None:
        reset_state()

    def test_health_returns_ok(self) -> None:
        client = _build_test_app()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_health_ok_even_when_container_not_ready(self) -> None:
        """Liveness probe must always succeed regardless of DI state."""
        client = _build_test_app()
        resp = client.get("/health")
        assert resp.status_code == 200


class TestReadyEndpoint:
    def setup_method(self) -> None:
        reset_state()

    def test_ready_returns_503_before_container_init(self) -> None:
        client = _build_test_app()
        resp = client.get("/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "not_ready"

    def test_ready_returns_200_after_container_set(self) -> None:
        set_container(object())
        client = _build_test_app()
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}

    def test_ready_returns_503_with_error_message(self) -> None:
        set_container_error("Not logged in — run: sophia auth login")
        client = _build_test_app()
        resp = client.get("/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "not_ready"
        assert "Not logged in" in body["error"]

    def test_reset_clears_state(self) -> None:
        set_container(object())
        reset_state()
        client = _build_test_app()
        resp = client.get("/ready")
        assert resp.status_code == 503


class TestGetContainer:
    def setup_method(self) -> None:
        reset_state()

    def test_returns_none_before_init(self) -> None:
        assert get_container() is None

    def test_returns_container_after_set(self) -> None:
        sentinel = object()
        set_container(sentinel)
        assert get_container() is sentinel

    def test_returns_none_after_reset(self) -> None:
        set_container(object())
        reset_state()
        assert get_container() is None

    def test_returns_none_after_error(self) -> None:
        set_container(object())
        set_container_error("boom")
        assert get_container() is None
