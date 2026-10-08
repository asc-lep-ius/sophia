"""Keep the shared TU Wien session alive from inside the API, and renew it when it dies.

TUWEL forgets a session after 8 h idle (``core_session_time_remaining`` read
28 800 s on 2026-10-08), and TISS says nothing about its lifetime. NiceGUI's
SessionHealthMonitor pinged TUWEL every 300 s until #102 deleted it with the
GUI, and nothing else ever took the job.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import httpx
import structlog

from sophia.adapters.auth import (
    KeyringUnavailableError,
    load_session,
    load_tiss_session,
    session_path,
    tiss_session_path,
)
from sophia.adapters.tiss_registration import TissRegistrationAdapter
from sophia.domain.errors import AuthError, NetworkError, RegistrationError
from sophia.services.tiss_registration import current_semester
from sophia.services.upstream_session import UpstreamStatus, reauthenticate

if TYPE_CHECKING:
    from collections.abc import Callable

    from sophia.adapters.auth import SessionCredentials
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# A refused login is retried 10 min later, then 20, 40 … up to every 6 h:
# soon enough to heal a transient IdP fault, slow enough that a wrong password
# or secret does not pile failed MFA attempts onto the learner's account.
BACKOFF_BASE_S = 600.0
BACKOFF_CAP_S = 6 * 3600.0

_UNREACHABLE = (httpx.HTTPError, NetworkError, RegistrationError, TimeoutError)


class SessionKeepalive:
    def __init__(
        self,
        container: AppContainer,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._container = container
        self._clock = clock
        self._failures = 0
        self._retry_at: float | None = None

    async def run(self, interval_s: float) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.tick()
            except Exception:
                # A keepalive that dies quietly is the failure it exists to end.
                log.exception("session_keepalive.tick_failed")

    async def tick(self) -> None:
        self._adopt_session_saved_elsewhere()
        try:
            await self._container.moodle.check_session()
            await self._ping_tiss()
        except AuthError as exc:
            log.info("session_keepalive.session_expired", reason=str(exc))
            await self._renew()
            return
        except _UNREACHABLE as exc:
            self._report(UpstreamStatus("unreachable", type(exc).__name__))
            return
        self._failures = 0
        self._retry_at = None
        self._report(UpstreamStatus("valid"))

    async def _ping_tiss(self) -> None:
        settings = self._container.settings
        credentials = load_tiss_session(tiss_session_path(settings.config_dir))
        if credentials is None:
            return
        adapter = TissRegistrationAdapter(
            http=self._container.http, credentials=credentials, host=settings.tiss_host
        )
        await adapter.get_favorites(current_semester())

    async def _renew(self) -> None:
        upstream = self._container.upstream
        if self._retry_at is not None and self._clock() < self._retry_at:
            self._report(UpstreamStatus("expired", upstream.status.reason))
            return
        settings = self._container.settings
        try:
            creds = await reauthenticate(
                settings.config_dir, settings.tuwel_host, settings.tiss_host, stale=upstream.creds
            )
        except (AuthError, KeyringUnavailableError) as exc:
            self._failures += 1
            delay = min(BACKOFF_BASE_S * 2 ** (self._failures - 1), BACKOFF_CAP_S)
            self._retry_at = self._clock() + delay
            self._report(UpstreamStatus("expired", str(exc)), retry_in_s=delay)
            return
        except _UNREACHABLE as exc:
            self._report(UpstreamStatus("unreachable", type(exc).__name__))
            return
        self._adopt(creds)
        self._failures = 0
        self._retry_at = None
        self._report(UpstreamStatus("valid"))
        log.info("session_keepalive.renewed")

    def _adopt_session_saved_elsewhere(self) -> None:
        """Pick up a session SESSION_CMD, a job or ``sophia auth login`` saved.

        Before #124 the API kept the cookie it started with until a restart,
        so a fresh login on the box changed nothing for it (#125).
        """
        held = self._container.upstream.creds
        on_disk = load_session(session_path(self._container.settings.config_dir))
        if on_disk is None or (held is not None and on_disk.moodle_session == held.moodle_session):
            return
        self._adopt(on_disk)
        # New credentials may well work where the old ones were refused.
        self._failures = 0
        self._retry_at = None
        log.info("session_keepalive.adopted_saved_session")

    def _adopt(self, creds: SessionCredentials) -> None:
        self._container.moodle.use_session(
            sesskey=creds.sesskey,
            moodle_session=creds.moodle_session,
            cookie_name=creds.cookie_name,
        )
        self._container.upstream.creds = creds

    def _report(self, status: UpstreamStatus, *, retry_in_s: float | None = None) -> None:
        upstream = self._container.upstream
        changed = status != upstream.status
        upstream.status = status
        if not changed:
            log.debug("session_keepalive.unchanged", state=status.state, retry_in_s=retry_in_s)
            return
        if status.state == "expired":
            # Once per transition: the reason is what the operator needs, and
            # repeating it every 5 min buries it.
            log.error("session_keepalive.expired", reason=status.reason, retry_in_s=retry_in_s)
        elif status.state == "unreachable":
            log.warning("session_keepalive.unreachable", reason=status.reason)
        else:
            log.info("session_keepalive.valid")
