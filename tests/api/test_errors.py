"""API error envelope tests."""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Query
from fastapi.testclient import TestClient

from sophia.api import create_api_app
from sophia.domain.errors import (
    AuthError,
    ChronosError,
    MoodleError,
    RegistrationError,
    SophiaError,
)


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_code"),
    [
        (AuthError("Not logged in"), 401, "auth.failed"),
        (MoodleError("Moodle exploded"), 502, "moodle.failed"),
        (RegistrationError("Registration closed"), 409, "registration.failed"),
        (ChronosError("Deadline sync failed"), 500, "chronos.failed"),
        (SophiaError("Generic domain message"), 500, "sophia.failed"),
    ],
)
def test_domain_errors_use_stable_envelope_without_raw_messages(
    exception: SophiaError,
    expected_status: int,
    expected_code: str,
) -> None:
    api_app = create_api_app()

    @api_app.get("/api/_raise-domain-error")
    async def raise_domain_error() -> None:
        raise exception

    response = TestClient(api_app).get("/api/_raise-domain-error")

    assert response.status_code == expected_status
    assert response.json() == {"detail": {"code": expected_code, "params": {}}}
    assert str(exception) not in response.text


def test_unknown_route_uses_stable_envelope_without_raw_message() -> None:
    response = TestClient(create_api_app()).get("/api/nope")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}
    assert response.json()["detail"] != "Not Found"
    assert "Not Found" not in response.text


def test_wrong_method_uses_stable_envelope_without_raw_message() -> None:
    response = TestClient(create_api_app()).put("/api/health")

    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.json() == {"detail": {"code": "http.method_not_allowed", "params": {}}}
    assert response.json()["detail"] != "Method Not Allowed"
    assert "Method Not Allowed" not in response.text


def test_validation_errors_use_stable_envelope_without_raw_messages() -> None:
    api_app = create_api_app()

    @api_app.get("/api/_validated")
    async def validated(value: Annotated[int, Query()]) -> dict[str, int]:
        return {"value": value}

    response = TestClient(api_app).get("/api/_validated", params={"value": "not-an-int"})

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}
    assert not isinstance(response.json()["detail"], str)
    assert "Input should be a valid integer" not in response.text
