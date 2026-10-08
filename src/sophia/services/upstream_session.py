"""The TU Wien session every process on the box shares, and how it comes back.

One TUWEL and one TISS session live in the config directory. The API,
SESSION_CMD and scheduled jobs all read them. MFA has been mandatory since
2026-04-01, so logging in again needs a code: the TOTP secret stored by
``sophia auth login --save-credentials`` generates one.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import structlog

from sophia.adapters.auth import (
    SessionCredentials,
    load_credentials_from_keyring,
    load_session,
    login_both,
    save_session,
    save_tiss_session,
    session_path,
    tiss_session_path,
)
from sophia.adapters.moodle import MoodleAdapter
from sophia.adapters.totp import StepLedger, fresh_code, ledger_path
from sophia.domain.errors import AuthError
from sophia.infra.http import http_session

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from pathlib import Path

log = structlog.get_logger()

_LOCK_FILENAME = ".reauth.lock"


class ReauthUnavailableError(AuthError):
    """Nothing stored that could log in again without a person."""


async def tuwel_session_alive(creds: SessionCredentials, tuwel_host: str) -> bool:
    """Whether TUWEL still accepts ``creds``. Network faults propagate.

    The check is ``core_session_time_remaining`` without ``nosessionupdate``,
    so a live session is also kept alive by asking.
    """
    async with http_session() as http:
        http.cookies.set(
            creds.cookie_name, creds.moodle_session, domain=urlparse(tuwel_host).hostname or ""
        )
        adapter = MoodleAdapter(
            http=http,
            sesskey=creds.sesskey,
            moodle_session=creds.moodle_session,
            host=tuwel_host,
            cookie_name=creds.cookie_name,
        )
        try:
            await adapter.check_session()
        except AuthError:
            return False
    return True


async def reauthenticate(
    config_dir: Path,
    tuwel_host: str,
    tiss_host: str,
    *,
    stale: SessionCredentials | None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SessionCredentials:
    """Log in with the stored password and a generated TOTP code, and save both sessions.

    ``stale`` is the TUWEL session the caller found dead. If the file holds a
    different one by the time the lock is held, another process has already
    logged in, and that session is returned without spending a code.

    Raises ReauthUnavailableError when no password or secret is stored,
    KeyringUnavailableError when the keyring cannot be read, and AuthError
    (MfaRejectedError for a refused code) when the IdP refuses the login.
    """
    async with _reauth_lock(config_dir):
        current = load_session(session_path(config_dir))
        if current is not None and await _refreshed_elsewhere(current, stale, tuwel_host):
            log.info("upstream_session.refreshed_elsewhere")
            return current

        stored = load_credentials_from_keyring()
        if stored is None:
            raise ReauthUnavailableError(
                "No TU Wien credentials stored — run: sophia auth login --save-credentials"
            )
        if not stored.totp_secret:
            raise ReauthUnavailableError(
                "No TOTP secret stored, so logging in again needs a person — run: "
                "sophia auth login --save-credentials and enter the secret"
            )

        code = await fresh_code(
            stored.totp_secret, StepLedger(ledger_path(config_dir)), clock=clock, sleep=sleep
        )
        log.info("upstream_session.re_authenticating")
        tuwel, tiss = await login_both(
            tuwel_host, tiss_host, stored.username, stored.password, code
        )
        save_session(tuwel, session_path(config_dir))
        if tiss is not None:
            save_tiss_session(tiss, tiss_session_path(config_dir))
        log.info("upstream_session.re_authenticated", tiss=tiss is not None)
        return tuwel


async def _refreshed_elsewhere(
    current: SessionCredentials, stale: SessionCredentials | None, tuwel_host: str
) -> bool:
    if stale is not None:
        return current.moodle_session != stale.moodle_session
    # The caller found no session at all; one has appeared while it waited.
    return await tuwel_session_alive(current, tuwel_host)


@contextlib.asynccontextmanager
async def _reauth_lock(config_dir: Path) -> AsyncIterator[None]:
    """One login at a time across every process on the box."""
    config_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(config_dir / _LOCK_FILENAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
