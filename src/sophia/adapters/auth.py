"""Session-based authentication for TUWEL/Moodle via pure HTTP SSO."""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import unquote

import httpx
import structlog
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from pathlib import Path

from sophia.domain.errors import AuthError

log = structlog.get_logger()

_SESSION_FILENAME = "tuwel_session.json"
_SESSKEY_RE = re.compile(r'"sesskey"\s*:\s*"([a-zA-Z0-9]+)"')

# TU Wien SSO entry point parameters
_SSO_IDP_ENTITY = "7bdd808f9f4da82bfe7992e779794b9a"
_SSO_LOGIN_PATH = "/auth/saml2/login.php"
_LAUNCH_PATH = "/admin/tool/mobile/launch.php"


@dataclass(frozen=True)
class SessionCredentials:
    """Stored TUWEL session credentials."""

    moodle_session: str
    sesskey: str
    host: str
    created_at: str
    cookie_name: str = "MoodleSession"
    ws_token: str | None = None


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
        return SessionCredentials(**data)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        log.warning("session_load_failed", path=str(path), error=str(exc))
        return None


def clear_session(path: Path) -> None:
    """Remove stored session credentials."""
    if path.exists():
        path.unlink()
        log.info("session_cleared", path=str(path))


async def acquire_ws_token(
    client: httpx.AsyncClient,
    base: str,
    cookie_name: str,
    moodle_session: str,
) -> str:
    """Obtain a WS token from Moodle's mobile launch endpoint.

    GETs launch.php with the session cookie (no redirect following),
    captures the ``moodlemobile://token=BASE64`` Location header,
    decodes the ``PASSPORT:::TOKEN:::PRIVATETOKEN`` payload.
    """
    passport = secrets.token_hex(8)
    url = f"{base}{_LAUNCH_PATH}"
    params = {"service": "moodle_mobile_app", "passport": passport}

    log.info("ws_token_acquire", url=url)
    resp = await client.get(
        url,
        params=params,
        cookies={cookie_name: moodle_session},
        follow_redirects=False,
    )

    location = resp.headers.get("location")
    if not location or "token=" not in location:
        raise AuthError("WS token acquisition failed — no redirect from launch.php")

    try:
        raw = location.split("token=", 1)[1]
        raw = unquote(raw)
        decoded = base64.b64decode(raw).decode("ascii")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise AuthError("WS token acquisition failed — invalid token payload") from exc

    parts = decoded.split(":::")
    if len(parts) < 2 or not parts[1]:
        raise AuthError("WS token acquisition failed — token not found in payload")

    log.info("ws_token_acquired")
    return parts[1]


async def login_with_credentials(host: str, username: str, password: str) -> SessionCredentials:
    """Authenticate via TU Wien SSO and return session credentials.

    Performs the full SAML SSO dance: initiate login -> submit credentials
    to the IdP -> relay SAML response back to TUWEL -> extract session.
    Then acquires a WS token for REST API access.
    """
    base = host.rstrip("/")
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        idp_resp = await _initiate_sso(client, base)
        saml_resp = await _submit_credentials(client, idp_resp, username, password)
        dashboard_resp = await _relay_saml_response(client, saml_resp)
        creds = _build_credentials(client, dashboard_resp, base)

        try:
            ws_token = await acquire_ws_token(client, base, creds.cookie_name, creds.moodle_session)
            return replace(creds, ws_token=ws_token)
        except AuthError:
            log.warning("ws_token_acquisition_failed", host=base)
            return creds


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
    """Find and POST the SAMLResponse + RelayState back to the SP."""
    soup = BeautifulSoup(resp.text, "lxml")

    saml_input = soup.find("input", {"name": "SAMLResponse"})
    relay_input = soup.find("input", {"name": "RelayState"})
    if not saml_input or not relay_input:
        raise AuthError("SSO failed — no SAML response received from IdP")

    saml_form = saml_input.find_parent("form")  # type: ignore[union-attr]
    if not saml_form or not saml_form.get("action"):
        raise AuthError("SSO failed — SAML response form has no action URL")

    acs_url = str(saml_form["action"])
    payload = {
        "SAMLResponse": saml_input["value"],  # type: ignore[index]
        "RelayState": relay_input["value"],  # type: ignore[index]
    }

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


def _extract_hidden_inputs(form: BeautifulSoup) -> dict[str, str]:
    """Collect all hidden input values from a form."""
    return {
        str(inp["name"]): str(inp.get("value", ""))
        for inp in form.find_all("input", {"type": "hidden"})
        if inp.get("name")
    }


def _resolve_url(current_url: str, action: str) -> str:
    """Resolve a potentially relative form action against the current URL."""
    if action.startswith("http"):
        return action
    from urllib.parse import urljoin

    return urljoin(current_url, action)
