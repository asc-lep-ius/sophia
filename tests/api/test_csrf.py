"""CSRF dependency tests for unsafe authenticated routes."""

from __future__ import annotations

from ._session_helpers import build_harness, csrf_headers, login


def test_unsafe_mutation_rejects_missing_requested_with_header() -> None:
    harness = build_harness()
    login(harness)
    token = csrf_headers(harness)["X-CSRF-Token"]

    response = harness.client.patch(
        "/api/settings",
        json={"theme": "dark"},
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_unsafe_mutation_rejects_missing_csrf_token_header() -> None:
    harness = build_harness()
    login(harness)

    response = harness.client.patch(
        "/api/settings",
        json={"theme": "dark"},
        headers={"X-Requested-With": "fetch"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_unsafe_mutation_rejects_mismatched_csrf_token_header() -> None:
    harness = build_harness()
    login(harness)

    response = harness.client.patch(
        "/api/settings",
        json={"theme": "dark"},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "not-the-session-token"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_logout_is_an_unsafe_authenticated_mutation() -> None:
    harness = build_harness()
    login(harness)

    response = harness.client.post("/api/auth/logout")

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}
