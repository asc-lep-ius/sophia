"""Session authentication commands."""

from __future__ import annotations

import cyclopts

app = cyclopts.App(name="auth", help="Session authentication commands.")


@app.command
async def login(*, save_credentials: bool = False) -> None:
    """Log in to TUWEL and TISS via TU Wien SSO (single prompt).

    Use --save-credentials to store your username/password in the OS
    keyring for automatic re-authentication in scheduled jobs.
    """
    import getpass
    import os

    from rich.console import Console
    from rich.prompt import Prompt

    from sophia.adapters.auth import (
        login_both,
        save_session,
        save_tiss_session,
        session_path,
        tiss_session_path,
    )
    from sophia.config import Settings

    console = Console()
    settings = Settings()

    username = os.environ.get("SOPHIA_TUWEL_USERNAME") or Prompt.ask(
        "TU Wien username", console=console
    )
    password = getpass.getpass("TU Wien password: ")

    tuwel_creds, tiss_creds = await login_both(
        settings.tuwel_host, settings.tiss_host, username, password
    )

    save_session(tuwel_creds, session_path(settings.config_dir))
    console.print("[green]TUWEL session saved.[/green]")

    if save_credentials:
        from sophia.adapters.auth import KeyringUnavailableError, save_credentials_to_keyring

        try:
            save_credentials_to_keyring(username, password)
        except KeyringUnavailableError:
            console.print(
                "[yellow]No keyring backend found. Credentials NOT saved.[/yellow]\n"
                "Install 'secretstorage' (Linux) or 'keyrings.alt' for file-based storage."
            )

    if tiss_creds:
        save_tiss_session(tiss_creds, tiss_session_path(settings.config_dir))
        console.print("[green]TISS session saved.[/green]")
    else:
        console.print(
            "[yellow]TUWEL login succeeded but TISS login failed. "
            "TISS features may be unavailable.[/yellow]"
        )


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
    """Clear stored session credentials and keyring."""
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
