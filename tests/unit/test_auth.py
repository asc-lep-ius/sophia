"""Tests for session authentication utilities."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx
import keyring
import pytest
import respx
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

from sophia.adapters.auth import (
    KeyringUnavailableError,
    SessionCredentials,
    StoredCredentials,
    _keyring_env_password,  # pyright: ignore[reportPrivateUsage]
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
from sophia.domain.errors import AuthError, MfaRejectedError

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
    <input type="number" name="totp" />
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


class MemoryKeyring(KeyringBackend):
    """A keyring that lives in the test, so no test can touch the box's real one."""

    priority = 1  # pyright: ignore[reportAssignmentType]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.store.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


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
    async def test_submits_mfa_code_when_idp_form_requests_totp(self):
        """TU Wien IdP MFA field is submitted as the form's totp value."""
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )

        def assert_login_payload(request: httpx.Request) -> httpx.Response:
            payload = parse_qs(request.content.decode())
            assert payload["username"] == ["testuser"]
            assert payload["password"] == ["testpass"]
            assert payload["totp"] == ["123456"]
            return httpx.Response(200, text=SAML_RESPONSE_HTML)

        respx.post(IDP_URL).mock(side_effect=assert_login_payload)
        respx.post(ACS_URL).mock(
            return_value=httpx.Response(
                200,
                text=DASHBOARD_HTML,
                headers={"set-cookie": "MoodleSession=test-moodle-session; path=/"},
            )
        )

        result = await login_with_credentials(HOST, "testuser", "testpass", "123456")

        assert result.moodle_session == "test-moodle-session"

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

    @pytest.mark.parametrize(
        "refusal",
        [
            "Ungültiger MFA Code — Der MFA Code fehlt oder ist ungültig",
            "Invalid MFA code — the MFA code is missing or invalid",
        ],
    )
    @respx.mock
    async def test_refused_mfa_code_is_reported_as_mfa_failure(self, refusal: str):
        """Since MFA became mandatory, a refused code must not read as a wrong password."""
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )
        refused = IDP_LOGIN_FORM_HTML.replace("<form", f'<div class="alert">{refusal}</div><form')
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=refused))

        with pytest.raises(MfaRejectedError, match="refused the MFA code"):
            await login_with_credentials(HOST, "testuser", "testpass", "000000")

    @respx.mock
    async def test_mfa_field_label_alone_is_not_an_mfa_refusal(self):
        """The form always labels its MFA field; only the refusal wording counts."""
        respx.get(f"{HOST}/auth/saml2/login.php").mock(
            return_value=httpx.Response(200, text=IDP_LOGIN_FORM_HTML)
        )
        labelled = IDP_LOGIN_FORM_HTML.replace(
            '<input type="number"', '<label>MFA Code</label><input type="number"'
        )
        respx.post(IDP_URL).mock(return_value=httpx.Response(200, text=labelled))

        with pytest.raises(AuthError, match="invalid username or password") as caught:
            await login_with_credentials(HOST, "baduser", "badpass", "123456")
        assert not isinstance(caught.value, MfaRejectedError)

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


class TestAuthLoginCommand:
    """CLI login prompt behavior."""

    async def test_prompts_for_mfa_code_and_passes_it_to_login_both(self, tmp_path: Path):
        from sophia.cli.auth import login

        tuwel_creds = SessionCredentials(
            moodle_session="test-moodle-session",
            sesskey="abc123sesskey",
            host=HOST,
            created_at="2026-03-04T12:00:00+00:00",
        )
        login_both_mock = AsyncMock(return_value=(tuwel_creds, None))
        settings = SimpleNamespace(
            tuwel_host=HOST,
            tiss_host=TISS_HOST,
            config_dir=tmp_path,
        )

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("rich.prompt.Prompt.ask", return_value="testuser"),
            patch("getpass.getpass", side_effect=["testpass", "123456"]),
            patch("sophia.config.Settings", return_value=settings),
            patch("sophia.adapters.auth.login_both", login_both_mock),
            patch("sophia.adapters.auth.save_session"),
        ):
            await login()

        login_both_mock.assert_awaited_once_with(HOST, TISS_HOST, "testuser", "testpass", "123456")

    async def _login_saving_credentials(
        self, tmp_path: Path, typed: list[str]
    ) -> tuple[AsyncMock, Path]:
        from sophia.cli.auth import login

        tuwel_creds = SessionCredentials(
            moodle_session="test-moodle-session",
            sesskey="abc123sesskey",
            host=HOST,
            created_at="2026-03-04T12:00:00+00:00",
        )
        login_both_mock = AsyncMock(return_value=(tuwel_creds, None))
        settings = SimpleNamespace(tuwel_host=HOST, tiss_host=TISS_HOST, config_dir=tmp_path)
        with (
            patch.dict("os.environ", {"PYTHON_KEYRING_BACKEND": "tests.MemoryKeyring"}, clear=True),
            patch("rich.prompt.Prompt.ask", return_value="testuser"),
            patch("getpass.getpass", side_effect=typed),
            patch("sophia.config.Settings", return_value=settings),
            patch("sophia.adapters.auth.login_both", login_both_mock),
        ):
            await login(save_credentials=True)
        return login_both_mock, tmp_path

    async def test_stores_a_totp_secret_that_produced_the_typed_code(
        self, tmp_path: Path, memory_keyring: MemoryKeyring
    ):
        import time

        from sophia.adapters.totp import StepLedger, code_for_step, ledger_path, step_at

        secret = "JBSWY3DPEHPK3PXP"
        code = code_for_step(secret, step_at(time.time()))

        await self._login_saving_credentials(tmp_path, ["testpass", code, secret])

        stored = load_credentials_from_keyring()
        assert stored is not None
        assert stored.totp_secret == secret
        # The typed code is spent, so a re-login in this step must wait.
        assert StepLedger(ledger_path(tmp_path)).last_used() is not None

    async def test_secret_that_did_not_produce_the_code_is_never_stored(
        self, tmp_path: Path, memory_keyring: MemoryKeyring
    ):
        """A wrong secret would only surface hours later, as a refused re-login."""
        import time

        from sophia.adapters.totp import code_for_step, step_at

        code = code_for_step("JBSWY3DPEHPK3PXP", step_at(time.time()))

        login_both_mock, _ = await self._login_saving_credentials(
            tmp_path, ["testpass", code, "GEZDGNBVGY3TQOJQ", ""]
        )

        login_both_mock.assert_awaited_once()
        assert load_credentials_from_keyring() == StoredCredentials("testuser", "testpass")


class TestKeyringCredentials:
    """Keyring credential save/load/clear with mocked backend."""

    def test_save_and_load_roundtrip(self, memory_keyring: MemoryKeyring):
        save_credentials_to_keyring("testuser", "testpass")

        assert load_credentials_from_keyring() == StoredCredentials("testuser", "testpass")

    def test_totp_secret_roundtrips_under_a_pinned_backend(self, memory_keyring: MemoryKeyring):
        with patch.dict("os.environ", {"PYTHON_KEYRING_BACKEND": "tests.MemoryKeyring"}):
            save_credentials_to_keyring("testuser", "testpass", "JBSWY3DPEHPK3PXP")

        loaded = load_credentials_from_keyring()
        assert loaded is not None
        assert loaded.totp_secret == "JBSWY3DPEHPK3PXP"

    def test_secrets_stay_out_of_the_repr(self):
        shown = repr(StoredCredentials("testuser", "hunter2", "JBSWY3DPEHPK3PXP"))
        assert "hunter2" not in shown
        assert "JBSWY3DPEHPK3PXP" not in shown

    def test_totp_secret_refused_without_a_pinned_backend(self, memory_keyring: MemoryKeyring):
        """#111: the backend is named explicitly, never left to priority resolution."""
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(KeyringUnavailableError, match="PYTHON_KEYRING_BACKEND"),
        ):
            save_credentials_to_keyring("testuser", "testpass", "JBSWY3DPEHPK3PXP")
        assert memory_keyring.store == {}

    def test_totp_secret_refused_by_a_plaintext_backend(self):
        """With the secret stored the box holds both factors, so cleartext is out."""
        plaintext_keyring = type("PlaintextKeyring", (), {"__module__": "keyrings.alt.file"})

        with (
            patch.dict(
                "os.environ", {"PYTHON_KEYRING_BACKEND": "keyrings.alt.file.PlaintextKeyring"}
            ),
            patch("keyring.get_keyring", return_value=plaintext_keyring()),
            patch("keyring.set_password") as set_password,
            pytest.raises(KeyringUnavailableError, match="PlaintextKeyring"),
        ):
            save_credentials_to_keyring("testuser", "testpass", "JBSWY3DPEHPK3PXP")
        set_password.assert_not_called()

    def test_saving_without_a_secret_removes_an_older_one(self, memory_keyring: MemoryKeyring):
        with patch.dict("os.environ", {"PYTHON_KEYRING_BACKEND": "tests.MemoryKeyring"}):
            save_credentials_to_keyring("testuser", "oldpass", "JBSWY3DPEHPK3PXP")
        save_credentials_to_keyring("testuser", "newpass")

        assert load_credentials_from_keyring() == StoredCredentials("testuser", "newpass")

    def test_wrong_master_password_is_reported_not_raised_raw(self):
        """keyrings.alt raises ValueError("Incorrect Password"); #111's note saw it crash."""
        with (
            patch("keyring.get_password", side_effect=ValueError("Incorrect Password")),
            pytest.raises(KeyringUnavailableError, match="master password"),
        ):
            load_credentials_from_keyring()

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

    def test_clear_removes_password_and_totp_secret(self, memory_keyring: MemoryKeyring):
        with patch.dict("os.environ", {"PYTHON_KEYRING_BACKEND": "tests.MemoryKeyring"}):
            save_credentials_to_keyring("testuser", "testpass", "JBSWY3DPEHPK3PXP")

        clear_credentials_from_keyring()

        assert memory_keyring.store == {}

    def test_clear_ignores_missing(self):
        """clear_credentials_from_keyring tolerates missing entries."""
        import keyring.errors

        def fake_delete(service: str, key: str) -> None:
            raise keyring.errors.PasswordDeleteError("not found")

        with patch("keyring.delete_password", side_effect=fake_delete):
            clear_credentials_from_keyring()  # Should not raise

    def test_save_raises_on_no_backend(self):
        """save_credentials_to_keyring raises KeyringUnavailableError when no backend."""
        import keyring.errors

        with (
            patch(
                "keyring.set_password",
                side_effect=keyring.errors.NoKeyringError("No backend"),
            ),
            pytest.raises(KeyringUnavailableError, match="No keyring backend"),
        ):
            save_credentials_to_keyring("user", "pass")

    def test_load_returns_none_on_no_backend(self):
        """load_credentials_from_keyring returns None when no backend."""
        import keyring.errors

        with patch(
            "keyring.get_password",
            side_effect=keyring.errors.NoKeyringError("No backend"),
        ):
            assert load_credentials_from_keyring() is None

    def test_clear_ignores_no_backend(self):
        """clear_credentials_from_keyring tolerates missing keyring backend."""
        import keyring.errors

        with patch(
            "keyring.delete_password",
            side_effect=keyring.errors.NoKeyringError("No backend"),
        ):
            clear_credentials_from_keyring()  # Should not raise

    def test_keyring_env_password_patches_getpass(self):
        """_keyring_env_password patches getpass when env var is set."""
        import getpass

        original = getpass.getpass
        with (
            patch.dict("os.environ", {"SOPHIA_KEYRING_PASSWORD": "test-pw"}),
            _keyring_env_password(),
        ):
            assert getpass.getpass() == "test-pw"
        assert getpass.getpass is original

    def test_keyring_env_password_noop_without_env(self):
        """_keyring_env_password is a no-op when env var is not set."""
        import getpass
        import os

        original = getpass.getpass
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("SOPHIA_KEYRING_PASSWORD", None)
            with _keyring_env_password():
                assert getpass.getpass is original
