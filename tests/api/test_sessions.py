"""Redis-backed opaque session core tests."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from sophia.api.sessions import (
    InvalidSessionToken,
    RedisSessionStore,
    SecretKeySessionManager,
    SessionCore,
    SessionCredential,
    SessionRecord,
    SessionSettings,
    SessionTenant,
    SessionUser,
    deserialize_session_record,
    dumps_session_record,
    serialize_session_record,
    sign_session_cookie,
)
from sophia.config import Settings

VALID_CURRENT_KEY = "current-session-signing-key-32-bytes"
VALID_PREVIOUS_KEY = "previous-session-signing-key-32-bytes"


class FakeRedis:
    """Small async Redis fake with enough TTL behavior for session tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expires_at: dict[str, int] = {}
        self.now = 0
        self.get_calls = 0

    async def set(
        self,
        name: str,
        value: str,
        ex: int | None = None,
        *,
        xx: bool = False,
        keepttl: bool = False,
    ) -> bool:
        self._purge(name)
        if xx and name not in self.values:
            return False
        current_expiry = self.expires_at.get(name)
        self.values[name] = value
        if keepttl:
            if current_expiry is not None:
                self.expires_at[name] = current_expiry
            else:
                self.expires_at.pop(name, None)
        elif ex is None:
            self.expires_at.pop(name, None)
        else:
            self.expires_at[name] = self.now + ex
        return True

    async def get(self, name: str) -> str | None:
        self.get_calls += 1
        self._purge(name)
        return self.values.get(name)

    async def delete(self, *names: str) -> int:
        deleted_count = 0
        for name in names:
            self._purge(name)
            if name in self.values:
                deleted_count += 1
                self.values.pop(name)
                self.expires_at.pop(name, None)
        return deleted_count

    async def expire(self, name: str, time: int) -> bool:
        self._purge(name)
        if name not in self.values:
            return False
        self.expires_at[name] = self.now + time
        return True

    async def ttl(self, name: str) -> int:
        self._purge(name)
        if name not in self.values:
            return -2
        expires_at = self.expires_at.get(name)
        if expires_at is None:
            return -1
        return max(expires_at - self.now, 0)

    def advance(self, seconds: int) -> None:
        self.now += seconds
        for name in tuple(self.values):
            self._purge(name)

    def _purge(self, name: str) -> None:
        expires_at = self.expires_at.get(name)
        if expires_at is not None and expires_at <= self.now:
            self.values.pop(name, None)
            self.expires_at.pop(name, None)


def test_session_settings_validate_cookie_and_redis_defaults() -> None:
    settings = Settings.model_validate({"session_cookie_samesite": "Lax"})

    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.session_cookie_name == "__Host-sophia_session"
    assert settings.csrf_cookie_name == "__Host-sophia_csrf"
    assert settings.session_ttl_seconds == 60 * 60 * 8
    assert settings.session_cookie_secure is True
    assert settings.session_cookie_samesite == "lax"

    with pytest.raises(ValueError, match="session_ttl_seconds"):
        Settings(session_ttl_seconds=59)
    with pytest.raises(ValueError, match="cookie name"):
        Settings(session_cookie_name="bad cookie")
    with pytest.raises(ValueError, match="__Host-"):
        Settings(session_cookie_secure=False)


async def test_opaque_session_create_read_refresh_delete_uses_signed_cookie() -> None:
    redis = FakeRedis()
    store = RedisSessionStore(redis=redis, ttl_seconds=900)
    core = SessionCore(
        store=store,
        signer=SecretKeySessionManager(current_key=VALID_CURRENT_KEY),
    )
    record = _session_record(session_id="opaque-session-id")

    cookie_value = await core.create(record)

    assert cookie_value != record.session_id
    assert set(redis.values) == {"sophia:session:opaque-session-id"}
    assert cookie_value not in redis.values
    assert await store.ttl(record.session_id) == 900
    assert await core.read(cookie_value) == record

    assert await core.refresh(cookie_value) == record
    assert await store.ttl(record.session_id) == 900
    assert await core.delete(cookie_value) is True
    assert await core.read(cookie_value) is None


async def test_session_store_preserves_ttl_on_save_and_refreshes_explicitly() -> None:
    redis = FakeRedis()
    store = RedisSessionStore(redis=redis, ttl_seconds=600)
    record = _session_record(session_id="session-to-update")
    await store.create(record)
    redis.advance(37)

    updated_record = replace(
        record,
        settings=SessionSettings(theme="dark", locale="de", selected_learning_path_id="course-2"),
    )
    assert await store.save(updated_record) is True

    assert await store.ttl(record.session_id) == 563
    assert await store.read(record.session_id) == updated_record

    assert await store.refresh(record.session_id) is True
    assert await store.ttl(record.session_id) == 600


async def test_session_store_save_does_not_resurrect_deleted_session() -> None:
    redis = FakeRedis()
    store = RedisSessionStore(redis=redis, ttl_seconds=600)
    record = _session_record(session_id="deleted-session")
    await store.create(record)
    assert await store.delete(record.session_id) is True

    updated_record = replace(record, settings=SessionSettings(theme="dark", locale="en"))

    assert await store.save(updated_record) is False
    assert await store.read(record.session_id) is None
    assert redis.values == {}


async def test_session_store_save_does_not_resurrect_expired_session() -> None:
    redis = FakeRedis()
    store = RedisSessionStore(redis=redis, ttl_seconds=120)
    record = _session_record(session_id="expired-session")
    await store.create(record)
    redis.advance(121)

    updated_record = replace(record, settings=SessionSettings(theme="dark", locale="en"))

    assert await store.save(updated_record) is False
    assert await store.read(record.session_id) is None
    assert redis.values == {}


async def test_fake_redis_expires_session_records_after_ttl() -> None:
    redis = FakeRedis()
    store = RedisSessionStore(redis=redis, ttl_seconds=120)
    record = _session_record(session_id="short-lived-session")

    await store.create(record)
    redis.advance(121)

    assert await store.read(record.session_id) is None
    assert await store.ttl(record.session_id) == -2


async def test_invalid_signed_cookie_is_rejected_before_store_lookup() -> None:
    redis = FakeRedis()
    core = SessionCore(
        store=RedisSessionStore(redis=redis, ttl_seconds=900),
        signer=SecretKeySessionManager(current_key=VALID_CURRENT_KEY),
    )

    with pytest.raises(InvalidSessionToken):
        await core.read("not-a-signed-session-cookie")

    assert redis.get_calls == 0


async def test_session_cookie_verifies_with_previous_key_after_rotation() -> None:
    redis = FakeRedis()
    store = RedisSessionStore(redis=redis, ttl_seconds=900)
    record = _session_record(session_id="rotated-session")
    await store.create(record)
    previous_signer = SecretKeySessionManager(current_key=VALID_PREVIOUS_KEY)
    rotating_core = SessionCore(
        store=store,
        signer=SecretKeySessionManager(
            current_key=VALID_CURRENT_KEY,
            previous_keys=(VALID_PREVIOUS_KEY,),
        ),
    )

    previous_cookie = sign_session_cookie(record.session_id, previous_signer)

    assert await rotating_core.read(previous_cookie) == record


def test_session_record_round_trips_as_json_compatible_payload() -> None:
    record = _session_record(
        session_id="record-round-trip",
        tuwel_credentials=SessionCredential(reference="secret:tuwel", payload={"username": "mn"}),
        tiss_credentials=SessionCredential(payload={"token": "serialized", "scopes": ["read"]}),
    )

    payload = serialize_session_record(record)
    json_payload = json.dumps(payload)

    assert payload["user"] == {"id": "learner-1", "display_name": "Learner One", "email": ""}
    assert payload["tenant"] == {
        "org_id": "tu-wien",
        "learning_path_id": "course-1",
        "cohort_id": "cohort-a",
        "role": "student",
    }
    assert deserialize_session_record(json.loads(json_payload)) == record
    assert dumps_session_record(record) == json_payload


def _session_record(
    *,
    session_id: str,
    tuwel_credentials: SessionCredential | None = None,
    tiss_credentials: SessionCredential | None = None,
) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        user=SessionUser(id="learner-1", display_name="Learner One"),
        csrf_token="csrf-token",
        tenant=SessionTenant(
            org_id="tu-wien",
            learning_path_id="course-1",
            cohort_id="cohort-a",
            role="student",
        ),
        settings=SessionSettings(theme="system", locale="en", selected_learning_path_id="course-1"),
        tuwel_credentials=tuwel_credentials,
        tiss_credentials=tiss_credentials,
        created_at="2026-05-25T00:00:00Z",
        updated_at="2026-05-25T00:00:00Z",
    )
