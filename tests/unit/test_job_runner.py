"""Tests for the job runner service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from sophia.adapters.auth import KeyringUnavailableError, SessionCredentials
from sophia.domain.errors import MfaRejectedError
from sophia.services.job_runner import ensure_valid_session
from sophia.services.upstream_session import ReauthUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

TUWEL_HOST = "https://tuwel.tuwien.ac.at"
TISS_HOST = "https://tiss.tuwien.ac.at"

STORED = SessionCredentials(
    moodle_session="stored-cookie",
    sesskey="key",
    host=TUWEL_HOST,
    created_at="2026-10-08T00:00:00+00:00",
)


class TestEnsureValidSession:
    async def test_live_session_needs_no_login(self, tmp_path: Path) -> None:
        reauth = AsyncMock()
        with (
            patch("sophia.services.job_runner.load_session", return_value=STORED),
            patch("sophia.services.job_runner.tuwel_session_alive", AsyncMock(return_value=True)),
            patch("sophia.services.job_runner.reauthenticate", reauth),
        ):
            assert await ensure_valid_session(tmp_path, TUWEL_HOST, TISS_HOST) is True
        reauth.assert_not_awaited()

    async def test_dead_session_is_renewed_and_named_as_the_stale_one(self, tmp_path: Path) -> None:
        reauth = AsyncMock(return_value=STORED)
        with (
            patch("sophia.services.job_runner.load_session", return_value=STORED),
            patch("sophia.services.job_runner.tuwel_session_alive", AsyncMock(return_value=False)),
            patch("sophia.services.job_runner.reauthenticate", reauth),
        ):
            assert await ensure_valid_session(tmp_path, TUWEL_HOST, TISS_HOST) is True
        reauth.assert_awaited_once_with(tmp_path, TUWEL_HOST, TISS_HOST, stale=STORED)

    async def test_missing_session_file_is_renewed_too(self, tmp_path: Path) -> None:
        reauth = AsyncMock(return_value=STORED)
        with (
            patch("sophia.services.job_runner.load_session", return_value=None),
            patch("sophia.services.job_runner.reauthenticate", reauth),
        ):
            assert await ensure_valid_session(tmp_path, TUWEL_HOST, TISS_HOST) is True
        reauth.assert_awaited_once_with(tmp_path, TUWEL_HOST, TISS_HOST, stale=None)

    @pytest.mark.parametrize(
        "failure",
        [
            ReauthUnavailableError("No TOTP secret stored"),
            MfaRejectedError("refused the MFA code"),
            KeyringUnavailableError("master password does not unlock the store"),
            httpx.ConnectError("idp unreachable"),
        ],
    )
    async def test_a_session_that_cannot_be_renewed_is_false_with_its_reason_logged(
        self, tmp_path: Path, failure: Exception
    ) -> None:
        with (
            patch("sophia.services.job_runner.load_session", return_value=None),
            patch("sophia.services.job_runner.reauthenticate", AsyncMock(side_effect=failure)),
            patch("sophia.services.job_runner.log") as log,
        ):
            assert await ensure_valid_session(tmp_path, TUWEL_HOST, TISS_HOST) is False
        log.error.assert_called_once()
        assert log.error.call_args.kwargs["reason"] == str(failure)
