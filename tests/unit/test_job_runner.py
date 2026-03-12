"""Tests for the job runner service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

from sophia.domain.errors import AuthError
from sophia.services.job_runner import ensure_valid_session

TUWEL_HOST = "https://tuwel.tuwien.ac.at"
TISS_HOST = "https://tiss.tuwien.ac.at"


def _make_session_creds() -> MagicMock:
    creds = MagicMock()
    creds.cookie_name = "MoodleSession"
    creds.moodle_session = "test-cookie"
    creds.sesskey = "test-sesskey"
    return creds


class TestEnsureValidSession:
    async def test_returns_true_when_session_valid(self, tmp_path: Path) -> None:
        """Existing session passes check_session — no keyring needed."""
        mock_creds = _make_session_creds()

        mock_http = AsyncMock()
        mock_http.cookies = MagicMock()

        mock_adapter = AsyncMock()
        mock_adapter.check_session = AsyncMock()

        with (
            patch("sophia.services.job_runner.load_session", return_value=mock_creds),
            patch("sophia.services.job_runner.http_session") as mock_http_ctx,
            patch("sophia.services.job_runner.MoodleAdapter", return_value=mock_adapter),
        ):
            mock_http_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await ensure_valid_session(tmp_path, TUWEL_HOST, TISS_HOST)

        assert result is True
        mock_adapter.check_session.assert_awaited_once()

    async def test_returns_false_when_no_session_and_no_keyring(self, tmp_path: Path) -> None:
        """No session file and no keyring creds → False."""
        with (
            patch("sophia.services.job_runner.load_session", return_value=None),
            patch(
                "sophia.services.job_runner.load_credentials_from_keyring",
                return_value=None,
            ),
        ):
            result = await ensure_valid_session(tmp_path, TUWEL_HOST, TISS_HOST)

        assert result is False

    async def test_re_authenticates_from_keyring_on_expired_session(self, tmp_path: Path) -> None:
        """Session expired but keyring has creds — re-auth succeeds."""
        mock_creds = _make_session_creds()
        new_tuwel = MagicMock()
        new_tiss = MagicMock()

        mock_http = AsyncMock()
        mock_http.cookies = MagicMock()

        mock_adapter = AsyncMock()
        mock_adapter.check_session = AsyncMock(side_effect=AuthError("expired"))

        with (
            patch("sophia.services.job_runner.load_session", return_value=mock_creds),
            patch("sophia.services.job_runner.http_session") as mock_http_ctx,
            patch("sophia.services.job_runner.MoodleAdapter", return_value=mock_adapter),
            patch(
                "sophia.services.job_runner.load_credentials_from_keyring",
                return_value=("user", "pass"),
            ),
            patch(
                "sophia.services.job_runner.login_both",
                new_callable=AsyncMock,
                return_value=(new_tuwel, new_tiss),
            ) as mock_login,
            patch("sophia.services.job_runner.save_session") as mock_save,
            patch("sophia.services.job_runner.save_tiss_session") as mock_save_tiss,
            patch(
                "sophia.services.job_runner.session_path",
                return_value=tmp_path / "tuwel.json",
            ),
            patch(
                "sophia.services.job_runner.tiss_session_path",
                return_value=tmp_path / "tiss.json",
            ),
        ):
            mock_http_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await ensure_valid_session(tmp_path, TUWEL_HOST, TISS_HOST)

        assert result is True
        mock_login.assert_awaited_once_with(TUWEL_HOST, TISS_HOST, "user", "pass")
        mock_save.assert_called_once_with(new_tuwel, tmp_path / "tuwel.json")
        mock_save_tiss.assert_called_once_with(new_tiss, tmp_path / "tiss.json")

    async def test_returns_false_when_re_auth_fails(self, tmp_path: Path) -> None:
        """Session expired and keyring re-auth also fails → False."""
        with (
            patch("sophia.services.job_runner.load_session", return_value=None),
            patch(
                "sophia.services.job_runner.load_credentials_from_keyring",
                return_value=("user", "pass"),
            ),
            patch(
                "sophia.services.job_runner.login_both",
                new_callable=AsyncMock,
                side_effect=AuthError("bad creds"),
            ),
        ):
            result = await ensure_valid_session(tmp_path, TUWEL_HOST, TISS_HOST)

        assert result is False
