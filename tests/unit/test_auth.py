"""Tests for session authentication utilities."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

if TYPE_CHECKING:
    from pathlib import Path

from unittest.mock import patch

from sophia.adapters.auth import (
    SessionCredentials,
    clear_credentials_from_keyring,
    clear_session,
    load_credentials_from_keyring,
    load_session,
    login_both,
    login_with_credentials,
    save_credentials_to_keyring,
    save_session,
    session_path,
)
from sophia.domain.errors import AuthError

HOST = "https://tuwel.tuwien.ac.at"
IDP_URL = "https://idp.zid.tuwien.ac.at/simplesaml/module.php/core/loginuserpass.php"
ACS_URL = f"{HOST}/auth/saml2/sp/saml2-acs.php/tuwel.tuwien.ac.at"


# --- HTML fixtures for mocking the SSO flow ---

IDP_LOGIN_FORM_HTML = f"""
<html><body>
<form method="post" action="{IDP_URL}">
  <input type="hidden" name="csrf_token" value="fake-csrf-token" />
  <input type="hidden" name="AuthState" value="fake-auth-state" />
  <input type="text" name="username" />
  <input type="password" name="password" />
  <button type="submit" name="_eventId_proceed">Login</button>
</form>
</body></html>
"""

SAML_RESPONSE_HTML = f"""
<html><body>
<form method="post" action="{ACS_URL}">
  <input type="hidden" name="SAMLResponse" value="fake-saml-response-b64" />
  <input type="hidden" name="RelayState" value="fake-relay-state" />
</form>
<script>document.forms[0].submit();</script>
</body></html>
"""

DASHBOARD_HTML = """
<html><head>
<script>M.cfg = {"sesskey":"abc123sesskey","loadingicon":"..."};</script>
</head><body>
<div id="page-wrapper">Dashboard content</div>
</body></html>
"""


@pytest.fixture
def creds() -> SessionCredentials:
    return SessionCredentials(
        moodle_session="abc123cookie",
        sesskey="xyz789key",
        host="https://tuwel.tuwien.ac.at",
        created_at="2026-03-04T12:00:00+00:00",
    )


class TestSessionPath:
    def test_returns_path_in_config_dir(self, tmp_path: Path):
        path = session_path(tmp_path)
        assert path.parent == tmp_path
        assert path.name == "tuwel_session.json"


class TestSaveAndLoadSession:
    def test_roundtrip(self, tmp_path: Path, creds: SessionCredentials):
        path = session_path(tmp_path)
        save_session(creds, path)
        loaded = load_session(path)
        assert loaded == creds

    def test_file_permissions(self, tmp_path: Path, creds: SessionCredentials):
        path = session_path(tmp_path)
        save_session(creds, path)
        assert oct(path.stat().st_mode & 0o777) == "0o600"

    def test_creates_parent_directories(self, tmp_path: Path, creds: SessionCredentials):
        path = tmp_path / "nested" / "dir" / "session.json"
        save_session(creds, path)
        assert path.exists()

    def test_load_missing_file_returns_none(self, tmp_path: Path):
        result = load_session(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_corrupt_json_returns_none(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("not valid json{{{")
        result = load_session(path)
        assert result is None

    def test_load_wrong_schema_returns_none(self, tmp_path: Path):
        path = tmp_path / "wrong.json"
        path.write_text(json.dumps({"wrong": "keys"}))
        result = load_session(path)
        assert result is None

    def test_load_old_session_with_extra_fields(self, tmp_path: Path):
        """Sessions saved before ws_token removal load gracefully."""
        path = tmp_path / "old_session.json"
        old_data = {
            "moodle_session": "abc123cookie",
            "sesskey": "xyz789key",
            "host": "https://tuwel.tuwien.ac.at",
            "created_at": "2026-03-04T12:00:00+00:00",
            "cookie_name": "MoodleSession",
            "ws_token": "stale_token",
        }
        path.write_text(json.dumps(old_data))
        loaded = load_session(path)
        assert loaded is not None
        assert loaded.moodle_session == "abc123cookie"


class TestClearSession:
    def test_removes_file(self, tmp_path: Path, creds: SessionCredentials):
        path = session_path(tmp_path)
        save_session(creds, path)
        assert path.exists()
        clear_session(path)
        assert not path.exists()

    def test_no_error_if_file_missing(self, tmp_path: Path):
        clear_session(tmp_path / "nonexistent.json")  # Should not raise


class TestLoginWithCredentials:
    """Tests for the HTTP SSO login flow using respx to mock requests."""

    @respx.mock
    async def test_successful_login(self):
        """Full SSO flow: initiate -> submit creds -> relay SAML -> extract session."""
        # 1. Initiate SSO — returns IdP login form
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )

        # 2. Submit credentials — returns SAML auto-submit form
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=SAML_RESPONSE_HTML))

        # 3. Relay SAML response — returns dashboard with MoodleSession cookie
        respx.post(ACS_URL).mock(
            return_value=httpx.Response(
                200,
                text=DASHBOARD_HTML,
                headers={"set-cookie": "MoodleSession=test-moodle-session; path=/"},
            )
        )

        result = await login_with_credentials(HOST, "testuser", "testpass")

        assert result.moodle_session == "test-moodle-session"
        assert result.sesskey == "abc123sesskey"
        assert result.host == HOST
        assert result.cookie_name == "MoodleSession"

    @respx.mock
    async def test_custom_cookie_name(self):
        """TUWEL uses 'MoodleSessiontuwel' — verify we detect the suffix."""
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=SAML_RESPONSE_HTML))
        respx.post(ACS_URL).mock(
            return_value=httpx.Response(
                200,
                text=DASHBOARD_HTML,
                headers={"set-cookie": "MoodleSessiontuwel=custom-cookie-val; path=/"},
            )
        )

        result = await login_with_credentials(HOST, "testuser", "testpass")

        assert result.moodle_session == "custom-cookie-val"
        assert result.cookie_name == "MoodleSessiontuwel"

    @respx.mock
    async def test_bad_credentials_raises_auth_error(self):
        """IdP returns the login form again when credentials are wrong."""
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )

        # IdP echoes back the login form (bad credentials)
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML))

        with pytest.raises(AuthError, match="invalid username or password"):
            await login_with_credentials(HOST, "baduser", "badpass")

    @respx.mock
    async def test_missing_saml_response_raises_auth_error(self):
        """IdP returns a page without SAMLResponse (SSO misconfiguration)."""
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )

        # After credential submit, no SAML response — just some unrelated page
        no_saml_html = "<html><body><p>Something went wrong.</p></body></html>"
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=no_saml_html))

        with pytest.raises(AuthError, match="no SAML response"):
            await login_with_credentials(HOST, "testuser", "testpass")

    @respx.mock
    async def test_network_error_propagates(self):
        """Connection error during SSO initiation propagates as transport error."""
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with pytest.raises(httpx.ConnectError):
            await login_with_credentials(HOST, "testuser", "testpass")

    @respx.mock
    async def test_missing_moodle_session_cookie_raises_auth_error(self):
        """SAML completes but TUWEL doesn't set the MoodleSession cookie."""
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=SAML_RESPONSE_HTML))
        # Dashboard response without MoodleSession cookie
        respx.post(ACS_URL).mock(return_value=httpx.Response(200, text=DASHBOARD_HTML))

        with pytest.raises(AuthError, match="MoodleSession cookie not found"):
            await login_with_credentials(HOST, "testuser", "testpass")

    @respx.mock
    async def test_missing_sesskey_raises_auth_error(self):
        """Dashboard loads but sesskey is absent from the page."""
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=SAML_RESPONSE_HTML))
        no_sesskey_html = "<html><body><p>Dashboard without M.cfg</p></body></html>"
        respx.post(ACS_URL).mock(
            return_value=httpx.Response(
                200,
                text=no_sesskey_html,
                headers={"set-cookie": "MoodleSession=test-session; path=/"},
            )
        )

        with pytest.raises(AuthError, match="sesskey not found"):
            await login_with_credentials(HOST, "testuser", "testpass")


# --- TISS SSO HTML fixtures for login_both tests ---

TISS_HOST = "https://tiss.tuwien.ac.at"
TISS_ACS_URL = f"{TISS_HOST}/auth/saml2/sp/saml2-acs.php/tiss.tuwien.ac.at"

TISS_SAML_RESPONSE_HTML = f"""
<html><body>
<form method="post" action="{TISS_ACS_URL}">
  <input type="hidden" name="SAMLResponse" value="fake-tiss-saml-response-b64" />
</form>
<script>document.forms[0].submit();</script>
</body></html>
"""

TISS_DASHBOARD_HTML = """
<html><body><p>TISS Dashboard</p></body></html>
"""

TISS_EDUCATION_HTML = """
<html><body><p>Favorites</p></body></html>
"""


class TestLoginBoth:
    """Tests for the unified login_both() that authenticates TUWEL + TISS."""

    @respx.mock
    async def test_successful_unified_login(self):
        """Single credential prompt authenticates to both TUWEL and TISS."""
        # TUWEL SSO flow
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=SAML_RESPONSE_HTML))
        respx.post(ACS_URL).mock(
            return_value=httpx.Response(
                200,
                text=DASHBOARD_HTML,
                headers={"set-cookie": "MoodleSession=test-moodle-session; path=/"},
            )
        )

        # TISS SSO flow — IdP recognizes session, returns SAML auto-submit
        respx.get(f"{TISS_HOST}/admin/authentifizierung").mock(
            return_value=httpx.Response(200, text=TISS_SAML_RESPONSE_HTML)
        )
        respx.post(TISS_ACS_URL).mock(
            return_value=httpx.Response(
                200,
                text=TISS_DASHBOARD_HTML,
                headers={
                    "set-cookie": "JSESSIONID=tiss-jsid; path=/",
                },
            )
        )
        # _establish_education_session GET
        respx.get(f"{TISS_HOST}/education/favorites.xhtml").mock(
            return_value=httpx.Response(
                200,
                text=TISS_EDUCATION_HTML,
                headers={"set-cookie": "_tiss_session=tiss-sess-val; path=/"},
            )
        )

        tuwel_creds, tiss_creds = await login_both(
            tuwel_host=HOST,
            tiss_host=TISS_HOST,
            username="testuser",
            password="testpass",
        )

        assert tuwel_creds.moodle_session == "test-moodle-session"
        assert tuwel_creds.sesskey == "abc123sesskey"
        assert tiss_creds is not None
        assert tiss_creds.jsessionid == "tiss-jsid"
        assert tiss_creds.tiss_session == "tiss-sess-val"

    @respx.mock
    async def test_tuwel_succeeds_tiss_fails_returns_partial(self):
        """TUWEL login works but TISS fails — returns TUWEL creds and TISS error."""
        # TUWEL SSO flow succeeds
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=SAML_RESPONSE_HTML))
        respx.post(ACS_URL).mock(
            return_value=httpx.Response(
                200,
                text=DASHBOARD_HTML,
                headers={"set-cookie": "MoodleSession=test-moodle-session; path=/"},
            )
        )

        # TISS SSO flow fails — network error
        respx.get(f"{TISS_HOST}/admin/authentifizierung").mock(
            side_effect=httpx.ConnectError("TISS unreachable")
        )

        tuwel_creds, tiss_creds = await login_both(
            tuwel_host=HOST,
            tiss_host=TISS_HOST,
            username="testuser",
            password="testpass",
        )

        assert tuwel_creds.moodle_session == "test-moodle-session"
        assert tiss_creds is None


class TestKeyringCredentials:
    """Keyring credential save/load/clear with mocked backend."""

    def test_save_and_load_roundtrip(self):
        store: dict[tuple[str, str], str] = {}

        def fake_set(service: str, key: str, value: str) -> None:
            store[(service, key)] = value

        def fake_get(service: str, key: str) -> str | None:
            return store.get((service, key))

        with (
            patch("keyring.set_password", side_effect=fake_set),
            patch("keyring.get_password", side_effect=fake_get),
        ):
            save_credentials_to_keyring("testuser", "testpass")
            result = load_credentials_from_keyring()

        assert result == ("testuser", "testpass")

    def test_load_missing_returns_none(self):
        with patch("keyring.get_password", return_value=None):
            result = load_credentials_from_keyring()
        assert result is None

    def test_load_partial_returns_none(self):
        """If only username is stored (no password), return None."""

        def selective_get(service: str, key: str) -> str | None:
            if key == "username":
                return "testuser"
            return None

        with patch("keyring.get_password", side_effect=selective_get):
            result = load_credentials_from_keyring()
        assert result is None

    def test_clear_removes_both(self):
        deleted: list[tuple[str, str]] = []

        def fake_delete(service: str, key: str) -> None:
            deleted.append((service, key))

        with patch("keyring.delete_password", side_effect=fake_delete):
            clear_credentials_from_keyring()

        assert len(deleted) == 2

    def test_clear_ignores_missing(self):
        """clear_credentials_from_keyring tolerates missing entries."""
        import keyring.errors

        def fake_delete(service: str, key: str) -> None:
            raise keyring.errors.PasswordDeleteError("not found")

        with patch("keyring.delete_password", side_effect=fake_delete):
            clear_credentials_from_keyring()  # Should not raise
