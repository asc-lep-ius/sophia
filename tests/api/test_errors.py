"""API error envelope tests."""

from __future__ import annotations

import pytest
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
