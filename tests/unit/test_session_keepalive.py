"""The API's keepalive: ping TUWEL and TISS, renew a dead session, back off when refused."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from sophia.adapters.auth import (
    SessionCredentials,
    TissSessionCredentials,
    save_session,
    save_tiss_session,
    session_path,
    tiss_session_path,
)
from sophia.domain.errors import AuthError, MfaRejectedError
from sophia.services.session_keepalive import BACKOFF_BASE_S, SessionKeepalive
from sophia.services.upstream_session import UpstreamSession, UpstreamStatus

if TYPE_CHECKING:
    from pathlib import Path

    from sophia.infra.di import AppContainer

TUWEL = "https://tuwel.tuwien.ac.at"
TISS = "https://tiss.tuwien.ac.at"


def _tuwel(cookie: str) -> SessionCredentials:
    return SessionCredentials(
        moodle_session=cookie, sesskey=f"key-{cookie}", host=TUWEL, created_at="2026-10-08"
    )


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        held = _tuwel("held")
        save_session(held, session_path(tmp_path))
        self.moodle = SimpleNamespace(check_session=AsyncMock(), use_session=MagicMock())
        self.container = SimpleNamespace(
            settings=SimpleNamespace(config_dir=tmp_path, tuwel_host=TUWEL, tiss_host=TISS),
            http=MagicMock(),
            moodle=self.moodle,
            upstream=UpstreamSession(held, UpstreamStatus("valid")),
        )
        self.clock = Clock()
        self.keepalive = SessionKeepalive(cast("AppContainer", self.container), clock=self.clock)

    @property
    def upstream(self) -> UpstreamSession:
        return self.container.upstream


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


async def test_a_live_session_is_only_pinged(harness: Harness) -> None:
    reauth = AsyncMock()
    with patch("sophia.services.session_keepalive.reauthenticate", reauth):
        await harness.keepalive.tick()

    harness.moodle.check_session.assert_awaited_once()
    reauth.assert_not_awaited()
    assert harness.upstream.status == UpstreamStatus("valid")


async def test_a_dead_tuwel_session_is_renewed_and_swapped_in_without_a_restart(
    harness: Harness,
) -> None:
    harness.moodle.check_session.side_effect = AuthError("Session expired")
    held = harness.upstream.creds
    reauth = AsyncMock(return_value=_tuwel("fresh"))

    with patch("sophia.services.session_keepalive.reauthenticate", reauth):
        await harness.keepalive.tick()

    assert reauth.await_args is not None
    assert reauth.await_args.kwargs["stale"] == held
    harness.moodle.use_session.assert_called_once_with(
        sesskey="key-fresh", moodle_session="fresh", cookie_name="MoodleSession"
    )
    assert harness.upstream.creds == _tuwel("fresh")
    assert harness.upstream.status == UpstreamStatus("valid")


async def test_a_dead_tiss_session_is_renewed_too(harness: Harness, tmp_path: Path) -> None:
    save_tiss_session(
        TissSessionCredentials(jsessionid="j", tiss_session="t", host=TISS, created_at="x"),
        tiss_session_path(tmp_path),
    )
    tiss = MagicMock()
    tiss.get_favorites = AsyncMock(side_effect=AuthError("TISS session expired"))
    reauth = AsyncMock(return_value=_tuwel("fresh"))

    with (
        patch("sophia.services.session_keepalive.TissRegistrationAdapter", return_value=tiss),
        patch("sophia.services.session_keepalive.reauthenticate", reauth),
    ):
        await harness.keepalive.tick()

    reauth.assert_awaited_once()


async def test_a_refused_renewal_backs_off_exponentially_and_is_logged_once(
    harness: Harness,
) -> None:
    """Retrying a wrong secret every 5 min would pile failed MFA attempts on the account."""
    harness.moodle.check_session.side_effect = AuthError("Session expired")
    reauth = AsyncMock(side_effect=MfaRejectedError("the IdP refused the MFA code"))

    with (
        patch("sophia.services.session_keepalive.reauthenticate", reauth),
        patch("sophia.services.session_keepalive.log") as log,
    ):
        await harness.keepalive.tick()
        assert harness.upstream.status == UpstreamStatus("expired", "the IdP refused the MFA code")

        harness.clock.now = BACKOFF_BASE_S - 1
        await harness.keepalive.tick()
        assert reauth.await_count == 1, "retried inside the backoff window"

        harness.clock.now = BACKOFF_BASE_S
        await harness.keepalive.tick()
        assert reauth.await_count == 2

        harness.clock.now = BACKOFF_BASE_S + 2 * BACKOFF_BASE_S - 1
        await harness.keepalive.tick()
        assert reauth.await_count == 2, "the second wait should be twice the first"

    assert log.error.call_count == 1


async def test_an_unreachable_tuwel_is_not_a_dead_session(harness: Harness) -> None:
    harness.moodle.check_session.side_effect = httpx.ConnectError("no route")
    reauth = AsyncMock()

    with patch("sophia.services.session_keepalive.reauthenticate", reauth):
        await harness.keepalive.tick()

    reauth.assert_not_awaited()
    assert harness.upstream.status == UpstreamStatus("unreachable", "ConnectError")


async def test_a_session_saved_elsewhere_is_adopted_without_a_login(
    harness: Harness, tmp_path: Path
) -> None:
    """A fresh `sophia auth login` used to change nothing for a running API (#125)."""
    save_session(_tuwel("logged-in-by-hand"), session_path(tmp_path))
    reauth = AsyncMock()

    with patch("sophia.services.session_keepalive.reauthenticate", reauth):
        await harness.keepalive.tick()

    harness.moodle.use_session.assert_called_once_with(
        sesskey="key-logged-in-by-hand",
        moodle_session="logged-in-by-hand",
        cookie_name="MoodleSession",
    )
    reauth.assert_not_awaited()
