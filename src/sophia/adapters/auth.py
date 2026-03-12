"""Session-based authentication for TUWEL/Moodle via pure HTTP SSO."""

from __future__ import annotations

import json
import re
import warnings
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from random import randint
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunsplit

import httpx
import structlog
from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

if TYPE_CHECKING:
    from pathlib import Path

from sophia.domain.errors import AuthError

log = structlog.get_logger()

_SESSION_FILENAME = "tuwel_session.json"
_TISS_SESSION_FILENAME = "tiss_session.json"
_SESSKEY_RE = re.compile(r'"sesskey"\s*:\s*"([a-zA-Z0-9]+)"')

# TU Wien SSO entry point parameters
_SSO_IDP_ENTITY = "7bdd808f9f4da82bfe7992e779794b9a"
_SSO_LOGIN_PATH = "/auth/saml2/login.php"
_TISS_AUTH_PATH = "/admin/authentifizierung"


@dataclass(frozen=True)
class SessionCredentials:
    """Stored TUWEL session credentials."""

    moodle_session: str
    sesskey: str
    host: str
    created_at: str
    cookie_name: str = "MoodleSession"


@dataclass(frozen=True)
class TissSessionCredentials:
    """Stored TISS session credentials."""

    jsessionid: str
    tiss_session: str
    host: str
    created_at: str
    cookies: str = "{}"  # JSON-encoded dict of all session cookies


def session_path(config_dir: Path) -> Path:
    """Return the path to the stored session file."""
    return config_dir / _SESSION_FILENAME


def save_session(creds: SessionCredentials, path: Path) -> None:
    """Persist session credentials to disk with restricted permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(creds), indent=2))
    path.chmod(0o600)
    log.info("session_saved", path=str(path))


def load_session(path: Path) -> SessionCredentials | None:
    """Load session credentials from disk, or None if missing/corrupt."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        valid = {f.name for f in fields(SessionCredentials)}
        return SessionCredentials(**{k: v for k, v in data.items() if k in valid})
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        log.warning("session_load_failed", path=str(path), error=str(exc))
        return None


def clear_session(path: Path) -> None:
    """Remove stored session credentials."""
    if path.exists():
        path.unlink()
        log.info("session_cleared", path=str(path))


def tiss_session_path(config_dir: Path) -> Path:
    """Return the path to the stored TISS session file."""
    return config_dir / _TISS_SESSION_FILENAME


def save_tiss_session(creds: TissSessionCredentials, path: Path) -> None:
    """Persist TISS session credentials to disk with restricted permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(creds), indent=2))
    path.chmod(0o600)
    log.info("tiss_session_saved", path=str(path))


def load_tiss_session(path: Path) -> TissSessionCredentials | None:
    """Load TISS session credentials from disk, or None if missing/corrupt."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        valid = {f.name for f in fields(TissSessionCredentials)}
        return TissSessionCredentials(**{k: v for k, v in data.items() if k in valid})
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        log.warning("tiss_session_load_failed", path=str(path), error=str(exc))
        return None


def clear_tiss_session(path: Path) -> None:
    """Remove stored TISS session credentials."""
    if path.exists():
        path.unlink()
        log.info("tiss_session_cleared", path=str(path))


_KEYRING_SERVICE = "sophia-tuwien"
_KEYRING_USERNAME_KEY = "username"
_KEYRING_PASSWORD_KEY = "password"


class KeyringUnavailableError(Exception):
    """Raised when no keyring backend is available."""


def save_credentials_to_keyring(username: str, password: str) -> None:
    """Store TU Wien credentials in the OS keyring (opt-in).

    Raises KeyringUnavailableError if no backend is configured.
    """
    import keyring
    import keyring.errors

    try:
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME_KEY, username)
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_PASSWORD_KEY, password)
    except keyring.errors.NoKeyringError as exc:
        raise KeyringUnavailableError(
            "No keyring backend available. "
            "Install 'secretstorage' (Linux) or 'keyrings.alt' for a file-based fallback."
        ) from exc
    log.info("credentials_saved_to_keyring", service=_KEYRING_SERVICE)


def load_credentials_from_keyring() -> tuple[str, str] | None:
    """Load stored TU Wien credentials from the OS keyring, or None."""
    import keyring
    import keyring.errors

    try:
        username = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME_KEY)
        password = keyring.get_password(_KEYRING_SERVICE, _KEYRING_PASSWORD_KEY)
    except keyring.errors.NoKeyringError:
        log.warning("keyring_unavailable")
        return None
    if username and password:
        return username, password
    return None


def clear_credentials_from_keyring() -> None:
    """Remove stored TU Wien credentials from the OS keyring."""
    import contextlib

    import keyring
    import keyring.errors

    with contextlib.suppress(keyring.errors.PasswordDeleteError, keyring.errors.NoKeyringError):
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME_KEY)
    with contextlib.suppress(keyring.errors.PasswordDeleteError, keyring.errors.NoKeyringError):
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_PASSWORD_KEY)
    log.info("credentials_cleared_from_keyring", service=_KEYRING_SERVICE)


async def login_both(
    tuwel_host: str,
    tiss_host: str,
    username: str,
    password: str,
) -> tuple[SessionCredentials, TissSessionCredentials | None]:
    """Authenticate to both TUWEL and TISS with a single credential prompt.

    Performs the TUWEL SAML flow first, then reuses the same httpx client
    (which holds IdP cookies) to initiate the TISS SSO flow.  The IdP
    recognizes the existing session and skips the credential prompt.

    If TUWEL succeeds but TISS fails, returns (tuwel_creds, None) so the
    caller can still save the TUWEL session.
    """
    tuwel_base = tuwel_host.rstrip("/")
    tiss_base = tiss_host.rstrip("/")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        # --- TUWEL SAML flow ---
        idp_resp = await _initiate_sso(client, tuwel_base)
        saml_resp = await _submit_credentials(client, idp_resp, username, password)
        dashboard_resp = await _relay_saml_response(client, saml_resp)
        tuwel_creds = _build_credentials(client, dashboard_resp, tuwel_base)

        # --- TISS SSO flow (IdP cookies already present) ---
        tiss_creds: TissSessionCredentials | None = None
        try:
            auth_url = f"{tiss_base}{_TISS_AUTH_PATH}"
            log.info("tiss_sso_initiate", url=auth_url)
            tiss_idp_resp = await client.get(auth_url)
            tiss_idp_resp.raise_for_status()

            tiss_saml_resp = await _relay_saml_response(client, tiss_idp_resp)

            await _establish_education_session(client, tiss_base)
            tiss_creds = _build_tiss_credentials(client, tiss_saml_resp, tiss_base)
        except Exception:
            log.warning("tiss_login_failed_during_unified_login", exc_info=True)

        return tuwel_creds, tiss_creds


async def login_with_credentials(host: str, username: str, password: str) -> SessionCredentials:
    """Authenticate via TU Wien SSO and return session credentials.

    Performs the full SAML SSO dance: initiate login -> submit credentials
    to the IdP -> relay SAML response back to TUWEL -> extract session.
    """
    base = host.rstrip("/")
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        idp_resp = await _initiate_sso(client, base)
        saml_resp = await _submit_credentials(client, idp_resp, username, password)
        dashboard_resp = await _relay_saml_response(client, saml_resp)
        return _build_credentials(client, dashboard_resp, base)


async def _initiate_sso(client: httpx.AsyncClient, base: str) -> httpx.Response:
    """GET the SSO login URL; follows redirects to the IdP login form."""
    url = f"{base}{_SSO_LOGIN_PATH}"
    params = {"wants": "", "idp": _SSO_IDP_ENTITY, "passive": "off"}
    log.info("sso_initiate", url=url)
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    return resp


async def _submit_credentials(
    client: httpx.AsyncClient,
    idp_resp: httpx.Response,
    username: str,
    password: str,
) -> httpx.Response:
    """Parse the IdP login form and POST credentials."""
    soup = BeautifulSoup(idp_resp.text, "lxml")
    form = _find_login_form(soup)

    form_action = form.get("action") or str(idp_resp.url)
    action_url = _resolve_url(str(idp_resp.url), str(form_action))

    payload = _extract_hidden_inputs(form)
    payload["username"] = username
    payload["password"] = password

    log.info("sso_submit_credentials", url=action_url, user=username)
    resp = await client.post(action_url, data=payload)
    resp.raise_for_status()

    # Check if IdP returned the login form again (bad credentials)
    resp_soup = BeautifulSoup(resp.text, "lxml")
    if resp_soup.find("input", {"name": "username"}):
        raise AuthError("Login failed — invalid username or password")

    return resp


async def _relay_saml_response(client: httpx.AsyncClient, resp: httpx.Response) -> httpx.Response:
    """Find and POST the SAMLResponse (+ optional RelayState) back to the SP.

    TUWEL includes RelayState in the IdP response; TISS does not.
    Both are valid SAML flows — RelayState is optional per the spec.
    """
    soup = BeautifulSoup(resp.text, "lxml")

    saml_input = soup.find("input", {"name": "SAMLResponse"})
    if not saml_input:
        raise AuthError("SSO failed — no SAML response received from IdP")

    saml_form = saml_input.find_parent("form")  # type: ignore[union-attr]
    if not saml_form or not saml_form.get("action"):
        raise AuthError("SSO failed — SAML response form has no action URL")

    acs_url = str(saml_form["action"])
    payload: dict[str, object] = {
        "SAMLResponse": saml_input["value"],  # type: ignore[index]
    }
    relay_input = soup.find("input", {"name": "RelayState"})
    if relay_input:
        payload["RelayState"] = relay_input["value"]  # type: ignore[index]

    log.info("sso_relay_saml", acs_url=acs_url)
    dashboard = await client.post(acs_url, data=payload)
    dashboard.raise_for_status()
    return dashboard


def _build_credentials(
    client: httpx.AsyncClient, resp: httpx.Response, base: str
) -> SessionCredentials:
    """Extract MoodleSession cookie and sesskey from the final response."""
    # Find the MoodleSession cookie — Moodle instances may use a custom
    # suffix (e.g. "MoodleSessiontuwel" on tuwel.tuwien.ac.at).
    cookie_name, moodle_cookie = _find_moodle_cookie(client, resp)
    if not moodle_cookie:
        raise AuthError("Login completed but MoodleSession cookie not found")

    sesskey = _extract_sesskey(resp.text)
    return SessionCredentials(
        moodle_session=moodle_cookie,
        sesskey=sesskey,
        host=base,
        created_at=datetime.now(UTC).isoformat(),
        cookie_name=cookie_name,
    )


def _build_tiss_credentials(
    client: httpx.AsyncClient, resp: httpx.Response, base: str
) -> TissSessionCredentials:
    """Extract TISS session cookies from the authenticated response.

    Dumps the full cookie jar (including /education/ JSESSIONID established
    by ``_establish_education_session``) so the adapter can restore all
    cookies later without needing IdP cookies.
    """
    jsessionid = None
    tiss_session = None

    for name, value in client.cookies.items():
        if name == "JSESSIONID":
            jsessionid = value
        elif name == "_tiss_session":
            tiss_session = value

    # Fall back to Set-Cookie headers
    if not jsessionid or not tiss_session:
        all_responses = [*resp.history, resp]
        for r in all_responses:
            for header_val in r.headers.get_list("set-cookie"):
                cookie_part = header_val.split(";")[0]
                name, _, value = cookie_part.partition("=")
                if name == "JSESSIONID" and value and not jsessionid:
                    jsessionid = value
                elif name == "_tiss_session" and value and not tiss_session:
                    tiss_session = value

    if not jsessionid:
        raise AuthError("TISS login completed but JSESSIONID cookie not found")
    if not tiss_session:
        raise AuthError("TISS login completed but _tiss_session cookie not found")

    # Capture full cookie jar for cross-context session support
    all_cookies = {name: value for name, value in client.cookies.items()}

    return TissSessionCredentials(
        jsessionid=jsessionid,
        tiss_session=tiss_session,
        host=base,
        created_at=datetime.now(UTC).isoformat(),
        cookies=json.dumps(all_cookies),
    )


def _extract_sesskey(html: str) -> str:
    """Extract Moodle sesskey from dashboard HTML."""
    match = _SESSKEY_RE.search(html)
    if not match:
        raise AuthError("Login completed but sesskey not found in page")
    return match.group(1)


def _find_moodle_cookie(client: httpx.AsyncClient, resp: httpx.Response) -> tuple[str, str | None]:
    """Find the MoodleSession cookie regardless of suffix.

    Moodle instances often use a custom cookie name like 'MoodleSessiontuwel'.
    Checks the client cookie jar first, then falls back to Set-Cookie headers
    in the redirect chain and final response.

    Returns (cookie_name, cookie_value) or ('MoodleSession', None) if not found.
    """
    # 1. Client cookie jar (populated by httpx during redirects)
    for name, value in client.cookies.items():
        if name.startswith("MoodleSession"):
            return name, value

    # 2. Set-Cookie headers in redirect hops and final response
    all_responses = [*resp.history, resp]
    for r in all_responses:
        for header_val in r.headers.get_list("set-cookie"):
            if "MoodleSession" in header_val:
                # Parse "MoodleSessionXXX=value; path=/; ..."
                cookie_part = header_val.split(";")[0]  # "MoodleSessionXXX=value"
                name, _, value = cookie_part.partition("=")
                if name.startswith("MoodleSession") and value:
                    return name, value

    return "MoodleSession", None


def _find_login_form(soup: BeautifulSoup) -> BeautifulSoup:
    """Locate the IdP login form containing username/password fields."""
    username_input = soup.find("input", {"name": "username"})
    if not username_input:
        raise AuthError("SSO failed — IdP login form not found")

    form = username_input.find_parent("form")  # type: ignore[union-attr]
    if not form:
        raise AuthError("SSO failed — login inputs found but no parent form")
    return form  # type: ignore[return-value]


def _extract_hidden_inputs(form: Tag) -> dict[str, str]:
    """Collect all hidden input values from a form."""
    return {
        str(inp["name"]): str(inp.get("value", ""))
        for inp in form.find_all("input", {"type": "hidden"})
        if inp.get("name")
    }


async def _establish_education_session(client: httpx.AsyncClient, base: str) -> None:
    """Navigate to /education/ so the server issues a JSESSIONID for that context.

    Must be called while the client still holds IdP cookies (i.e. during
    the same ``login_both`` client session).  Handles the DeltaSpike
    "Loading" page the same way the adapter does at runtime.
    """
    education_url = f"{base}/education/favorites.xhtml"
    log.info("tiss_establish_education_session", url=education_url)

    resp = await client.get(education_url)
    resp.raise_for_status()

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(resp.text, "lxml")
    redirect_path = _extract_deltaspike_redirect(soup)
    if redirect_path:
        redirect_url = _build_auth_deltaspike_url(
            str(resp.url),
            redirect_path,
            client,
        )
        log.debug("tiss_education_deltaspike_redirect", url=redirect_url)
        resp = await client.get(redirect_url)
        resp.raise_for_status()

    log.info("tiss_education_session_established")


_DELTASPIKE_REDIRECT_RE = re.compile(r"var\s+redirectUrl\s*=\s*'([^']+)'")


def _extract_deltaspike_redirect(soup: BeautifulSoup) -> str | None:
    """Detect the DeltaSpike window-handler Loading page; return redirect URL."""
    title = soup.find("title")
    if not title or "Loading" not in title.get_text():
        return None
    for script in soup.find_all("script"):
        text = script.string or ""
        m = _DELTASPIKE_REDIRECT_RE.search(text)
        if m:
            return m.group(1).replace(r"\/", "/").encode("utf-8").decode("unicode_escape")
    return None


def _build_auth_deltaspike_url(
    base_url: str,
    redirect_path: str,
    client: httpx.AsyncClient,
) -> str:
    """Build DeltaSpike redirect URL with window-ID tokens (login-time)."""
    window_id = str(randint(1000, 9999))  # noqa: S311
    request_token = str(randint(0, 998))  # noqa: S311
    client.cookies.set(f"dsrwid-{request_token}", window_id)

    full_url = urljoin(base_url, redirect_path)
    parsed = urlparse(full_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["dsrid"] = [request_token]
    params["dswid"] = [window_id]
    new_query = urlencode(params, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, ""))


def _resolve_url(current_url: str, action: str) -> str:
    """Resolve a potentially relative form action against the current URL."""
    if action.startswith("http"):
        return action
    return urljoin(current_url, action)
