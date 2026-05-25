"""Auth/session route tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sophia.api.sessions import verify_session_cookie
from sophia.domain.errors import AuthError

from ._session_helpers import build_harness, csrf_headers, login

if TYPE_CHECKING:
    from sophia.api.routers.auth import LoginIdentity
    from sophia.api.schemas.auth import AuthLoginRequest
    from sophia.config import Settings


def test_login_sets_signed_session_and_csrf_cookies() -> None:
    harness = build_harness()

    response = harness.client.post(
        "/api/auth/login",
        json={"username": "learner", "password": "correct horse battery staple"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["user"] == {
        "id": "learner",
        "display_name": "Learner One",
        "email": "learner@example.test",
    }
    assert body["tenant"] == {
        "org_id": "tu-wien",
        "course_id": "course-1",
        "cohort_id": "cohort-a",
        "role": "student",
    }
    assert body["settings"] == {
        "theme": "system",
        "locale": "en",
        "selected_course_id": "course-1",
    }

    session_cookie = response.cookies.get(harness.settings.session_cookie_name)
    csrf_cookie = response.cookies.get(harness.settings.csrf_cookie_name)
    assert session_cookie is not None
    assert csrf_cookie == body["csrf_token"]
    assert verify_session_cookie(session_cookie, harness.core.signer) != session_cookie
    assert len(harness.redis.values) == 1

    set_cookie_headers = response.headers.get_list("set-cookie")
    session_header = _cookie_header(set_cookie_headers, harness.settings.session_cookie_name)
    csrf_header = _cookie_header(set_cookie_headers, harness.settings.csrf_cookie_name)
    assert "HttpOnly" in session_header
    assert "HttpOnly" not in csrf_header
    assert "Secure" in session_header
    assert "Secure" in csrf_header
    assert "SameSite=lax" in session_header
    assert "SameSite=lax" in csrf_header
    assert "Path=/" in session_header
    assert "Path=/" in csrf_header


def test_login_bad_credentials_uses_auth_error_envelope() -> None:
    async def reject_login(_payload: AuthLoginRequest, _settings: Settings) -> LoginIdentity:
        raise AuthError("invalid credentials")

    harness = build_harness(login_authenticator=reject_login)

    response = harness.client.post(
        "/api/auth/login",
        json={"username": "learner", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "auth.failed", "params": {}}}
    assert harness.settings.session_cookie_name not in response.cookies
    assert harness.redis.values == {}
    assert "invalid credentials" not in response.text


def test_session_endpoint_returns_authenticated_session() -> None:
    harness = build_harness()
    login(harness)

    response = harness.client.get("/api/auth/session")

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["user"]["id"] == "learner"
    assert body["tenant"]["org_id"] == "tu-wien"
    assert body["settings"]["selected_course_id"] == "course-1"
    assert body["csrf_token"] == harness.client.cookies.get(harness.settings.csrf_cookie_name)


def test_session_endpoint_without_cookie_returns_anonymous_status() -> None:
    response = build_harness().client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": False,
        "user": None,
        "tenant": None,
        "settings": None,
        "csrf_token": None,
    }


def test_login_rotates_and_deletes_existing_session() -> None:
    harness = build_harness()

    login(harness)
    first_cookie = harness.client.cookies.get(harness.settings.session_cookie_name)
    assert first_cookie is not None
    first_session_id = verify_session_cookie(first_cookie, harness.core.signer)

    login(harness)
    second_cookie = harness.client.cookies.get(harness.settings.session_cookie_name)
    assert second_cookie is not None
    second_session_id = verify_session_cookie(second_cookie, harness.core.signer)

    assert first_session_id != second_session_id
    assert f"sophia:session:{first_session_id}" not in harness.redis.values
    assert f"sophia:session:{second_session_id}" in harness.redis.values


def test_logout_deletes_session_and_clears_cookies() -> None:
    harness = build_harness()
    login(harness)
    cookie = harness.client.cookies.get(harness.settings.session_cookie_name)
    assert cookie is not None
    session_id = verify_session_cookie(cookie, harness.core.signer)

    response = harness.client.post("/api/auth/logout", headers=csrf_headers(harness))

    assert response.status_code == 204
    assert f"sophia:session:{session_id}" not in harness.redis.values
    assert harness.client.cookies.get(harness.settings.session_cookie_name) is None
    assert harness.client.cookies.get(harness.settings.csrf_cookie_name) is None
    clear_headers = response.headers.get_list("set-cookie")
    assert "Max-Age=0" in _cookie_header(clear_headers, harness.settings.session_cookie_name)
    assert "Max-Age=0" in _cookie_header(clear_headers, harness.settings.csrf_cookie_name)


def _cookie_header(headers: list[str], cookie_name: str) -> str:
    for header in headers:
        if header.startswith(f"{cookie_name}="):
            return header
    raise AssertionError(f"missing Set-Cookie header for {cookie_name}")
