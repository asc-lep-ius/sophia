"""Secret-key validation and session signing tests."""

from __future__ import annotations

import pytest

from sophia.api.sessions import InvalidSessionToken, SecretKeySessionManager, create_session_manager
from sophia.config import Settings

VALID_CURRENT_KEY = "current-session-signing-key-32-bytes"
VALID_PREVIOUS_KEY = "previous-session-signing-key-32-bytes"
VALID_LEGACY_KEY = "legacy-session-signing-key-32-bytes"


def test_local_settings_remain_usable_without_configured_secret_key() -> None:
    settings = Settings()

    settings.validate_secret_key_configuration()
    manager = create_session_manager(settings)
    token = manager.sign({"session_id": "local-session"})

    assert manager.verify(token) == {"session_id": "local-session"}


def test_production_secret_validation_requires_current_key() -> None:
    with pytest.raises(ValueError, match="SOPHIA_SECRET_KEY_CURRENT"):
        Settings(production=True)


def test_production_secret_validation_rejects_legacy_key_only() -> None:
    with pytest.raises(ValueError, match="SOPHIA_SECRET_KEY_CURRENT"):
        Settings(production=True, secret_key=VALID_LEGACY_KEY)


def test_production_secret_validation_rejects_previous_key_only() -> None:
    with pytest.raises(ValueError, match="SOPHIA_SECRET_KEY_CURRENT"):
        Settings(production=True, secret_key_previous=VALID_PREVIOUS_KEY)


def test_production_secret_validation_rejects_legacy_and_previous_without_current() -> None:
    with pytest.raises(ValueError, match="SOPHIA_SECRET_KEY_CURRENT"):
        Settings(
            production=True,
            secret_key=VALID_LEGACY_KEY,
            secret_key_previous=VALID_PREVIOUS_KEY,
        )


@pytest.mark.parametrize("short_key", ["short-current-key"])
def test_production_secret_validation_rejects_short_current_key(short_key: str) -> None:
    with pytest.raises(ValueError, match="at least 32"):
        Settings(production=True, secret_key_current=short_key)


def test_production_secret_validation_accepts_valid_current_key() -> None:
    settings = Settings(production=True, secret_key_current=VALID_CURRENT_KEY)

    settings.validate_secret_key_configuration()


def test_dual_key_sessions_sign_with_current_and_accept_previous() -> None:
    previous_manager = SecretKeySessionManager(current_key=VALID_PREVIOUS_KEY)
    rotating_manager = SecretKeySessionManager(
        current_key=VALID_CURRENT_KEY,
        previous_keys=(VALID_PREVIOUS_KEY,),
    )

    previous_token = previous_manager.sign({"session_id": "old"})
    current_token = rotating_manager.sign({"session_id": "new"})

    assert rotating_manager.verify(previous_token) == {"session_id": "old"}
    assert rotating_manager.verify(current_token) == {"session_id": "new"}
    with pytest.raises(InvalidSessionToken):
        previous_manager.verify(current_token)


def test_invalid_session_token_is_rejected() -> None:
    manager = SecretKeySessionManager(current_key=VALID_CURRENT_KEY)

    with pytest.raises(InvalidSessionToken):
        manager.verify("not-a-valid-token")


def test_settings_session_manager_uses_current_and_verifies_previous_and_legacy_keys() -> None:
    previous_manager = SecretKeySessionManager(current_key=VALID_PREVIOUS_KEY)
    legacy_manager = SecretKeySessionManager(current_key=VALID_LEGACY_KEY)
    settings = Settings(
        production=True,
        secret_key_current=VALID_CURRENT_KEY,
        secret_key_previous=VALID_PREVIOUS_KEY,
        secret_key=VALID_LEGACY_KEY,
    )

    manager = create_session_manager(settings)
    current_token = manager.sign({"session_id": "current"})
    previous_token = previous_manager.sign({"session_id": "previous"})
    legacy_token = legacy_manager.sign({"session_id": "legacy"})

    assert manager.verify(current_token) == {"session_id": "current"}
    assert manager.verify(previous_token) == {"session_id": "previous"}
    assert manager.verify(legacy_token) == {"session_id": "legacy"}
