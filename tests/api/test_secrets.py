"""Secret-key validation and session signing tests."""

from __future__ import annotations

import pytest

from sophia.api.sessions import InvalidSessionToken, SecretKeySessionManager, create_session_manager
from sophia.config import Settings


def test_local_settings_remain_usable_without_configured_secret_key() -> None:
    settings = Settings()

    settings.validate_secret_key_configuration()
    manager = create_session_manager(settings)
    token = manager.sign({"session_id": "local-session"})

    assert manager.verify(token) == {"session_id": "local-session"}


def test_production_secret_validation_fails_without_current_or_legacy_key() -> None:
    settings = Settings(production=True, secret_key_previous="previous-only")

    with pytest.raises(ValueError, match="SOPHIA_SECRET_KEY_CURRENT"):
        settings.validate_secret_key_configuration()


def test_production_secret_validation_accepts_current_or_legacy_key() -> None:
    Settings(production=True, secret_key_current="current-key").validate_secret_key_configuration()
    Settings(production=True, secret_key="legacy-key").validate_secret_key_configuration()


def test_dual_key_sessions_sign_with_current_and_accept_previous() -> None:
    previous_manager = SecretKeySessionManager(current_key="previous-key")
    rotating_manager = SecretKeySessionManager(
        current_key="current-key",
        previous_keys=("previous-key",),
    )

    previous_token = previous_manager.sign({"session_id": "old"})
    current_token = rotating_manager.sign({"session_id": "new"})

    assert rotating_manager.verify(previous_token) == {"session_id": "old"}
    assert rotating_manager.verify(current_token) == {"session_id": "new"}
    with pytest.raises(InvalidSessionToken):
        previous_manager.verify(current_token)


def test_invalid_session_token_is_rejected() -> None:
    manager = SecretKeySessionManager(current_key="current-key")

    with pytest.raises(InvalidSessionToken):
        manager.verify("not-a-valid-token")
