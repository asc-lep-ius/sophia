"""Session authentication commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import cyclopts

if TYPE_CHECKING:
    from rich.console import Console

app = cyclopts.App(name="auth", help="Session authentication commands.")


_TOTP_SECRET_ATTEMPTS = 3


@app.command
async def login(*, save_credentials: bool = False) -> None:
    """Log in to TUWEL and TISS via TU Wien SSO (single prompt).

    Use --save-credentials to store your username, password and TOTP secret in
    the OS keyring, so a session that dies is renewed without you: MFA is
    mandatory, and the secret is what generates the code.
    """
    import getpass
    import os
    import time

    from rich.console import Console
    from rich.prompt import Prompt

    from sophia.adapters.auth import (
        KeyringUnavailableError,
        login_both,
        require_secure_keyring,
        save_credentials_to_keyring,
        save_session,
        save_tiss_session,
        session_path,
        tiss_session_path,
    )
    from sophia.adapters.totp import StepLedger, ledger_path, step_at
    from sophia.config import Settings

    console = Console()
    settings = Settings()

    username = os.environ.get("SOPHIA_TUWEL_USERNAME") or Prompt.ask(
        "TU Wien username", console=console
    )
    password = getpass.getpass("TU Wien password: ")
    mfa_code = (
        os.environ.get("SOPHIA_TUWEL_MFA_CODE") or getpass.getpass("TU Wien MFA code: ")
    ).strip()
    if not (mfa_code.isdigit() and len(mfa_code) == 6):
        console.print("[red]TU Wien MFA code must be 6 digits.[/red]")
        raise SystemExit(1)

    totp_secret: str | None = None
    if save_credentials:
        try:
            require_secure_keyring()
        except KeyringUnavailableError as exc:
            console.print(f"[yellow]TOTP secret will not be stored: {exc}[/yellow]")
        else:
            totp_secret = _prompt_totp_secret(console, mfa_code)

    tuwel_creds, tiss_creds = await login_both(
        settings.tuwel_host, settings.tiss_host, username, password, mfa_code
    )
    # The code is spent now, so a re-login in this step waits for the next one.
    StepLedger(ledger_path(settings.config_dir)).record(step_at(time.time()))

    save_session(tuwel_creds, session_path(settings.config_dir))
    console.print("[green]TUWEL session saved.[/green]")

    if save_credentials:
        try:
            save_credentials_to_keyring(username, password, totp_secret)
        except KeyringUnavailableError as exc:
            console.print(f"[yellow]Credentials NOT saved: {exc}[/yellow]")
        else:
            if totp_secret is None:
                console.print(
                    "[yellow]Credentials saved without a TOTP secret — a session that "
                    "dies will need you to log in again.[/yellow]"
                )
            else:
                console.print("[green]Credentials and TOTP secret saved.[/green]")

    if tiss_creds:
        save_tiss_session(tiss_creds, tiss_session_path(settings.config_dir))
        console.print("[green]TISS session saved.[/green]")
    else:
        console.print(
            "[yellow]TUWEL login succeeded but TISS login failed. "
            "TISS features may be unavailable.[/yellow]"
        )


def _prompt_totp_secret(console: Console, mfa_code: str) -> str | None:
    """Ask for the authenticator's secret, and keep it only if it made ``mfa_code``.

    Checked against the code just typed, before anything is sent to the IdP: a
    wrong secret would otherwise surface hours later as a refused re-login.
    Read with getpass only — never from argv or the environment, where it would
    land in shell history or ``/proc``.
    """
    import getpass
    import time

    from sophia.adapters.totp import InvalidTotpSecretError, matching_step, normalize_secret

    for _ in range(_TOTP_SECRET_ATTEMPTS):
        raw = getpass.getpass(
            "TOTP secret (base32, from your authenticator's otpauth:// enrolment; Enter to skip): "
        )
        if not raw.strip():
            return None
        try:
            secret = normalize_secret(raw)
        except InvalidTotpSecretError as exc:
            console.print(f"[red]{exc}.[/red]")
            continue
        if matching_step(secret, mfa_code, time.time()) is None:
            console.print("[red]That secret does not produce the MFA code you entered.[/red]")
            continue
        return secret
    console.print("[yellow]No valid TOTP secret entered — it will not be stored.[/yellow]")
    return None


@app.command
async def status() -> None:
    """Check if the current session is valid."""
    from urllib.parse import urlparse

    from rich.console import Console

    from sophia.adapters.auth import load_session, session_path
    from sophia.adapters.moodle import MoodleAdapter
    from sophia.config import Settings
    from sophia.domain.errors import AuthError
    from sophia.infra.http import http_session

    console = Console()
    settings = Settings()
    creds = load_session(session_path(settings.config_dir))
    if creds is None:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1)

    async with http_session() as http:
        tuwel_domain = urlparse(settings.tuwel_host).hostname or ""
        http.cookies.set(creds.cookie_name, creds.moodle_session, domain=tuwel_domain)
        adapter = MoodleAdapter(
            http=http,
            sesskey=creds.sesskey,
            moodle_session=creds.moodle_session,
            host=settings.tuwel_host,
            cookie_name=creds.cookie_name,
        )
        try:
            await adapter.check_session()
            console.print("[green]Session is active.[/green]")
        except AuthError:
            console.print("[red]Not logged in — run:[/red] sophia auth login")
            raise SystemExit(1) from None


@app.command
def logout() -> None:
    """Clear stored sessions, and the password and TOTP secret in the keyring."""
    from rich.console import Console

    from sophia.adapters.auth import (
        clear_credentials_from_keyring,
        clear_session,
        clear_tiss_session,
        session_path,
        tiss_session_path,
    )
    from sophia.config import Settings

    console = Console()
    settings = Settings()
    clear_session(session_path(settings.config_dir))
    clear_tiss_session(tiss_session_path(settings.config_dir))
    clear_credentials_from_keyring()
    console.print("[green]Session and credentials cleared.[/green]")
