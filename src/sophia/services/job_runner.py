"""Job runner — executes scheduled jobs with automatic session renewal."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from pathlib import Path

from sophia.adapters.auth import KeyringUnavailableError, load_session, session_path
from sophia.domain.errors import AuthError
from sophia.services.upstream_session import reauthenticate, tuwel_session_alive

log = structlog.get_logger()


async def ensure_valid_session(config_dir: Path, tuwel_host: str, tiss_host: str) -> bool:
    """Check the stored TUWEL session, and log in again with a TOTP code if it died.

    Returns True when a valid session is stored afterwards (the existing one or
    a new one). Returns False, with the reason logged once at error, when the
    session is dead and cannot be renewed without a person.
    """
    creds = load_session(session_path(config_dir))
    try:
        if creds is not None and await tuwel_session_alive(creds, tuwel_host):
            log.info("job_runner.session_valid")
            return True
        log.info("job_runner.session_expired")
        await reauthenticate(config_dir, tuwel_host, tiss_host, stale=creds)
    except (AuthError, KeyringUnavailableError, httpx.HTTPError) as exc:
        log.error("job_runner.re_auth_failed", reason=str(exc), error=type(exc).__name__)
        return False
    log.info("job_runner.re_auth_success")
    return True
