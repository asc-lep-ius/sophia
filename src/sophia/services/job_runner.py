"""Job runner — executes scheduled jobs with automatic session renewal."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pathlib import Path

from sophia.adapters.auth import (
    load_credentials_from_keyring,
    load_session,
    login_both,
    save_session,
    save_tiss_session,
    session_path,
    tiss_session_path,
)
from sophia.adapters.moodle import MoodleAdapter
from sophia.domain.errors import AuthError
from sophia.infra.http import http_session

log = structlog.get_logger()


async def ensure_valid_session(config_dir: Path, tuwel_host: str, tiss_host: str) -> bool:
    """Check session validity and re-authenticate from keyring if expired.

    Returns True if a valid session is available (existing or refreshed).
    Returns False if no keyring credentials are stored and session is expired.
    """
    from urllib.parse import urlparse

    creds = load_session(session_path(config_dir))
    if creds is not None:
        try:
            async with http_session() as http:
                tuwel_domain = urlparse(tuwel_host).hostname or ""
                http.cookies.set(creds.cookie_name, creds.moodle_session, domain=tuwel_domain)
                adapter = MoodleAdapter(
                    http=http,
                    sesskey=creds.sesskey,
                    moodle_session=creds.moodle_session,
                    host=tuwel_host,
                    cookie_name=creds.cookie_name,
                )
                await adapter.check_session()
                log.info("job_runner.session_valid")
                return True
        except AuthError:
            log.info("job_runner.session_expired")

    keyring_creds = load_credentials_from_keyring()
    if keyring_creds is None:
        log.error("job_runner.no_keyring_credentials")
        return False

    username, password = keyring_creds
    log.info("job_runner.re_authenticating")

    try:
        tuwel_creds, tiss_creds = await login_both(tuwel_host, tiss_host, username, password)
        save_session(tuwel_creds, session_path(config_dir))
        if tiss_creds:
            save_tiss_session(tiss_creds, tiss_session_path(config_dir))
        log.info("job_runner.re_auth_success")
        return True
    except AuthError:
        log.error("job_runner.re_auth_failed", exc_info=True)
        return False
