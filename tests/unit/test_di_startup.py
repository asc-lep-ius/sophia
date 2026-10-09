"""create_app validates the stored TUWEL session before building anything."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from sophia.adapters.auth import SessionCredentials
from sophia.domain.errors import AuthError
from sophia.infra.di import _startup_session, create_app  # pyright: ignore[reportPrivateUsage]
from sophia.services.upstream_session import ReauthUnavailableError, UpstreamStatus

if TYPE_CHECKING:
    from pathlib import Path

    from sophia.config import Settings

TUWEL = "https://tuwel.tuwien.ac.at"
TISS = "https://tiss.tuwien.ac.at"
STORED = SessionCredentials(moodle_session="stored", sesskey="k", host=TUWEL, created_at="x")
RENEWED = SessionCredentials(moodle_session="renewed", sesskey="k2", host=TUWEL, created_at="y")


def _settings(tmp_path: Path) -> Settings:
    return cast("Settings", SimpleNamespace(config_dir=tmp_path, tuwel_host=TUWEL, tiss_host=TISS))


async def test_a_live_session_is_used_as_it_is(tmp_path: Path) -> None:
    reauth = AsyncMock()
    with (
        patch("sophia.infra.di.tuwel_session_alive", AsyncMock(return_value=True)),
        patch("sophia.infra.di.reauthenticate", reauth),
    ):
        upstream = await _startup_session(_settings(tmp_path), STORED)

    reauth.assert_not_awaited()
    assert upstream.creds == STORED
    assert upstream.status == UpstreamStatus("valid")


async def test_a_session_that_died_overnight_is_renewed_before_startup(tmp_path: Path) -> None:
    """The file only proves somebody logged in once; TUWEL forgets after 8 h idle."""
    reauth = AsyncMock(return_value=RENEWED)
    with (
        patch("sophia.infra.di.tuwel_session_alive", AsyncMock(return_value=False)),
        patch("sophia.infra.di.reauthenticate", reauth),
    ):
        upstream = await _startup_session(_settings(tmp_path), STORED)

    reauth.assert_awaited_once_with(tmp_path, TUWEL, TISS, stale=STORED)
    assert upstream.creds == RENEWED
    assert upstream.status == UpstreamStatus("valid")


async def test_a_session_that_cannot_be_renewed_starts_degraded_not_refused(
    tmp_path: Path,
) -> None:
    with (
        patch("sophia.infra.di.tuwel_session_alive", AsyncMock(return_value=False)),
        patch(
            "sophia.infra.di.reauthenticate",
            AsyncMock(side_effect=ReauthUnavailableError("No TOTP secret stored")),
        ),
    ):
        upstream = await _startup_session(_settings(tmp_path), STORED)

    assert upstream.creds == STORED
    assert upstream.status == UpstreamStatus("expired", "No TOTP secret stored")


async def test_an_unreachable_tuwel_does_not_block_startup(tmp_path: Path) -> None:
    with patch(
        "sophia.infra.di.tuwel_session_alive",
        AsyncMock(side_effect=httpx.ConnectError("no route")),
    ):
        upstream = await _startup_session(_settings(tmp_path), STORED)

    assert upstream.creds == STORED
    assert upstream.status == UpstreamStatus("unreachable", "ConnectError")


async def test_no_session_and_no_way_to_log_in_is_still_not_logged_in(tmp_path: Path) -> None:
    with (
        patch(
            "sophia.infra.di.reauthenticate",
            AsyncMock(side_effect=ReauthUnavailableError("No TU Wien credentials stored")),
        ),
        pytest.raises(AuthError, match="Not logged in"),
    ):
        async with create_app(_settings(tmp_path)):
            pass


async def test_create_app_builds_on_the_renewed_session_not_the_stale_file(
    tmp_path: Path,
) -> None:
    """create_app used to load the file and go; it has to validate and renew first."""
    from sophia.adapters.auth import save_session, session_path

    save_session(STORED, session_path(tmp_path))
    built_with: list[object] = []

    async def capture_init(_stack: object, _settings: object, upstream: object) -> object:
        built_with.append(upstream)
        return object()

    with (
        patch("sophia.infra.di.tuwel_session_alive", AsyncMock(return_value=False)),
        patch("sophia.infra.di.reauthenticate", AsyncMock(return_value=RENEWED)),
        patch("sophia.infra.di._init_resources", capture_init),
    ):
        async with create_app(_settings(tmp_path)):
            pass

    [upstream] = built_with
    assert getattr(upstream, "creds", None) == RENEWED
    assert getattr(upstream, "status", None) == UpstreamStatus("valid")


@pytest.mark.parametrize(
    "broken_setup",
    [
        PermissionError("config dir is not writable"),
        ValueError("Non-base32 digit found"),
    ],
)
async def test_a_broken_setup_starts_degraded_instead_of_crashing(
    tmp_path: Path, broken_setup: Exception
) -> None:
    """An unwritable config dir (#111) or a corrupt stored secret is reported, not fatal."""
    with (
        patch("sophia.infra.di.tuwel_session_alive", AsyncMock(return_value=False)),
        patch("sophia.infra.di.reauthenticate", AsyncMock(side_effect=broken_setup)),
    ):
        upstream = await _startup_session(_settings(tmp_path), STORED)

    assert upstream.creds == STORED
    assert upstream.status == UpstreamStatus("expired", str(broken_setup))
