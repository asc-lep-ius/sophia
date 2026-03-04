"""Tests for session authentication utilities."""

from __future__ import annotations

import base64 as _b64
import json
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

if TYPE_CHECKING:
    from pathlib import Path

from sophia.adapters.auth import (
    SessionCredentials,
    acquire_ws_token,
    clear_session,
    load_session,
    login_with_credentials,
    save_session,
    session_path,
)
from sophia.domain.errors import AuthError

HOST = "https://tuwel.tuwien.ac.at"
IDP_URL = "https://idp.zid.tuwien.ac.at/simplesaml/module.php/core/loginuserpass.php"
ACS_URL = f"{HOST}/auth/saml2/sp/saml2-acs.php/tuwel.tuwien.ac.at"

# WS token acquisition test data
LAUNCH_PATH = "/admin/tool/mobile/launch.php"
_WS_TOKEN = "test_ws_token_value"
_TOKEN_PAYLOAD = _b64.b64encode(f"testpassport:::{_WS_TOKEN}:::privatetok".encode()).decode()
_MOBILE_REDIRECT = f"moodlemobile://token={_TOKEN_PAYLOAD}"


def _mock_launch_php() -> None:
    """Register a respx mock for launch.php that returns a valid WS token redirect."""
    respx.get(f"{HOST}{LAUNCH_PATH}").mock(
        return_value=httpx.Response(303, headers={"location": _MOBILE_REDIRECT})
    )


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

    def test_roundtrip_preserves_ws_token(self, tmp_path: Path):
        creds_with_token = SessionCredentials(
            moodle_session="abc123cookie",
            sesskey="xyz789key",
            host="https://tuwel.tuwien.ac.at",
            created_at="2026-03-04T12:00:00+00:00",
            ws_token="my_ws_token",
        )
        path = session_path(tmp_path)
        save_session(creds_with_token, path)
        loaded = load_session(path)
        assert loaded is not None
        assert loaded.ws_token == "my_ws_token"

    def test_load_old_session_without_ws_token(self, tmp_path: Path):
        """Sessions saved before ws_token was added load with ws_token=None."""
        path = tmp_path / "old_session.json"
        old_data = {
            "moodle_session": "abc123cookie",
            "sesskey": "xyz789key",
            "host": "https://tuwel.tuwien.ac.at",
            "created_at": "2026-03-04T12:00:00+00:00",
            "cookie_name": "MoodleSession",
        }
        path.write_text(json.dumps(old_data))
        loaded = load_session(path)
        assert loaded is not None
        assert loaded.ws_token is None


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

        # 4. WS token acquisition via launch.php
        _mock_launch_php()

        result = await login_with_credentials(HOST, "testuser", "testpass")

        assert result.moodle_session == "test-moodle-session"
        assert result.sesskey == "abc123sesskey"
        assert result.host == HOST
        assert result.cookie_name == "MoodleSession"
        assert result.ws_token == _WS_TOKEN

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
        _mock_launch_php()

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


class TestAcquireWsToken:
    """Tests for WS token acquisition via launch.php."""

    @respx.mock
    async def test_successful_acquisition(self):
        respx.get(f"{HOST}{LAUNCH_PATH}").mock(
            return_value=httpx.Response(303, headers={"location": _MOBILE_REDIRECT})
        )
        async with httpx.AsyncClient() as client:
            token = await acquire_ws_token(client, HOST, "MoodleSession", "sess_val")
        assert token == _WS_TOKEN

    @respx.mock
    async def test_missing_location_header(self):
        respx.get(f"{HOST}{LAUNCH_PATH}").mock(
            return_value=httpx.Response(200, text="<html>no redirect</html>")
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(AuthError, match="no redirect"):
                await acquire_ws_token(client, HOST, "MoodleSession", "sess_val")

    @respx.mock
    async def test_invalid_base64(self):
        respx.get(f"{HOST}{LAUNCH_PATH}").mock(
            return_value=httpx.Response(
                303, headers={"location": "moodlemobile://token=!!!not-base64!!!"}
            )
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(AuthError, match="invalid token payload"):
                await acquire_ws_token(client, HOST, "MoodleSession", "sess_val")

    @respx.mock
    async def test_missing_token_in_payload(self):
        """Decoded payload has wrong format (no triple-colon separator)."""
        bad_payload = _b64.b64encode(b"just-a-passport-no-separators").decode()
        respx.get(f"{HOST}{LAUNCH_PATH}").mock(
            return_value=httpx.Response(
                303, headers={"location": f"moodlemobile://token={bad_payload}"}
            )
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(AuthError, match="token not found"):
                await acquire_ws_token(client, HOST, "MoodleSession", "sess_val")

    @respx.mock
    async def test_login_succeeds_without_ws_token(self):
        """Login completes gracefully when WS token acquisition fails."""
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
        # launch.php returns 200 instead of redirect — token acquisition fails
        respx.get(f"{HOST}{LAUNCH_PATH}").mock(
            return_value=httpx.Response(200, text="<html>error</html>")
        )

        result = await login_with_credentials(HOST, "testuser", "testpass")

        assert result.moodle_session == "test-moodle-session"
        assert result.ws_token is None
