"""Logging in again without a person: password plus a generated TOTP code."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from sophia.adapters.auth import (
    SessionCredentials,
    StoredCredentials,
    TissSessionCredentials,
    load_session,
    load_tiss_session,
    save_session,
    session_path,
    tiss_session_path,
)
from sophia.adapters.totp import StepLedger, code_for_step, ledger_path, step_at
from sophia.domain.errors import MfaRejectedError
from sophia.services.upstream_session import ReauthUnavailableError, reauthenticate

if TYPE_CHECKING:
    from pathlib import Path

TUWEL = "https://tuwel.tuwien.ac.at"
TISS = "https://tiss.tuwien.ac.at"
SECRET = "JBSWY3DPEHPK3PXP"
NOW = 1_800_000_010.0


def _tuwel(cookie: str) -> SessionCredentials:
    return SessionCredentials(
        moodle_session=cookie, sesskey="key", host=TUWEL, created_at="2026-10-08T00:00:00+00:00"
    )


def _tiss() -> TissSessionCredentials:
    return TissSessionCredentials(
        jsessionid="j", tiss_session="t", host=TISS, created_at="2026-10-08T00:00:00+00:00"
    )


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def stored() -> StoredCredentials:
    return StoredCredentials("e12345678", "pw", SECRET)


async def test_logs_in_with_the_password_and_a_generated_code(
    tmp_path: Path, stored: StoredCredentials
) -> None:
    dead = _tuwel("dead")
    save_session(dead, session_path(tmp_path))
    login = AsyncMock(return_value=(_tuwel("fresh"), _tiss()))
    clock = FakeClock(NOW)

    with (
        patch(
            "sophia.services.upstream_session.load_credentials_from_keyring", return_value=stored
        ),
        patch("sophia.services.upstream_session.login_both", login),
    ):
        result = await reauthenticate(
            tmp_path, TUWEL, TISS, stale=dead, clock=clock, sleep=clock.sleep
        )

    login.assert_awaited_once_with(
        TUWEL, TISS, "e12345678", "pw", code_for_step(SECRET, step_at(NOW))
    )
    assert result.moodle_session == "fresh"
    saved = load_session(session_path(tmp_path))
    assert saved is not None
    assert saved.moodle_session == "fresh"
    assert load_tiss_session(tiss_session_path(tmp_path)) is not None


async def test_a_session_another_process_saved_is_used_without_a_login(
    tmp_path: Path, stored: StoredCredentials
) -> None:
    """SESSION_CMD and the API share the files; two logins would spend two codes."""
    save_session(_tuwel("refreshed-elsewhere"), session_path(tmp_path))
    login = AsyncMock()
    clock = FakeClock(NOW)

    with (
        patch(
            "sophia.services.upstream_session.load_credentials_from_keyring", return_value=stored
        ),
        patch("sophia.services.upstream_session.login_both", login),
    ):
        result = await reauthenticate(
            tmp_path, TUWEL, TISS, stale=_tuwel("dead"), clock=clock, sleep=clock.sleep
        )

    login.assert_not_awaited()
    assert result.moodle_session == "refreshed-elsewhere"


async def test_waits_for_the_next_step_after_a_login_in_this_one(
    tmp_path: Path, stored: StoredCredentials
) -> None:
    StepLedger(ledger_path(tmp_path)).record(step_at(NOW))
    login = AsyncMock(return_value=(_tuwel("fresh"), None))
    clock = FakeClock(NOW)

    with (
        patch(
            "sophia.services.upstream_session.load_credentials_from_keyring", return_value=stored
        ),
        patch("sophia.services.upstream_session.login_both", login),
    ):
        await reauthenticate(tmp_path, TUWEL, TISS, stale=None, clock=clock, sleep=clock.sleep)

    assert clock.slept
    assert login.await_args is not None
    assert login.await_args.args[4] == code_for_step(SECRET, step_at(NOW) + 1)


@pytest.mark.parametrize(
    ("keyring_holds", "reason"),
    [
        (None, "No TU Wien credentials stored"),
        (StoredCredentials("e12345678", "pw", None), "No TOTP secret stored"),
    ],
)
async def test_without_a_stored_secret_there_is_no_password_only_login(
    tmp_path: Path, keyring_holds: StoredCredentials | None, reason: str
) -> None:
    """MFA is mandatory: a password-only login is refused by the IdP every time."""
    login = AsyncMock()
    clock = FakeClock(NOW)

    with (
        patch(
            "sophia.services.upstream_session.load_credentials_from_keyring",
            return_value=keyring_holds,
        ),
        patch("sophia.services.upstream_session.login_both", login),
        pytest.raises(ReauthUnavailableError, match=reason),
    ):
        await reauthenticate(tmp_path, TUWEL, TISS, stale=None, clock=clock, sleep=clock.sleep)

    login.assert_not_awaited()


async def test_a_refused_code_reaches_the_caller_as_an_mfa_failure(
    tmp_path: Path, stored: StoredCredentials
) -> None:
    clock = FakeClock(NOW)
    with (
        patch(
            "sophia.services.upstream_session.load_credentials_from_keyring", return_value=stored
        ),
        patch(
            "sophia.services.upstream_session.login_both",
            AsyncMock(side_effect=MfaRejectedError("refused the MFA code")),
        ),
        pytest.raises(MfaRejectedError),
    ):
        await reauthenticate(tmp_path, TUWEL, TISS, stale=None, clock=clock, sleep=clock.sleep)
