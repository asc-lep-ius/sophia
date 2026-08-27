"""Session signing and Redis-backed opaque session core for the backend API."""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, TypeGuard, cast

from itsdangerous import BadData, URLSafeSerializer

if TYPE_CHECKING:
    from sophia.config import Settings

SESSION_SALT = "sophia.api.session"
SESSION_COOKIE_CLAIM = "session_id"
SESSION_KEY_NAMESPACE = "sophia:session"
SESSION_RECORD_VERSION = 2
_TOKEN_BYTES = 32

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def _empty_json_object() -> JsonObject:
    return {}


class InvalidSessionToken(ValueError):
    """Raised when a session token cannot be verified."""


class RedisSessionBackend(Protocol):
    """Minimal async Redis surface used by the session store."""

    async def set(
        self,
        name: str,
        value: str,
        ex: int | None = None,
        *,
        xx: bool = False,
        keepttl: bool = False,
    ) -> object: ...

    async def get(self, name: str) -> bytes | str | None: ...

    async def delete(self, *names: str) -> int: ...

    async def expire(self, name: str, time: int) -> object: ...

    async def ttl(self, name: str) -> int: ...


class SessionStoreBackend(Protocol):
    """Store contract used by the opaque session core."""

    async def create(self, record: SessionRecord, ttl_seconds: int | None = None) -> None: ...

    async def read(self, session_id: str) -> SessionRecord | None: ...

    async def save(self, record: SessionRecord) -> bool: ...

    async def refresh(self, session_id: str, ttl_seconds: int | None = None) -> bool: ...

    async def delete(self, session_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class SessionUser:
    """Identity carried by a server-side session."""

    id: str
    display_name: str = ""
    email: str = ""

    def __post_init__(self) -> None:
        _require_non_empty("user.id", self.id)


@dataclass(frozen=True, slots=True)
class SessionTenant:
    """Org and learning-path scope carried by a server-side session."""

    org_id: str = "local"
    learning_path_id: str = "default-learning-path"
    cohort_id: str | None = None
    role: str = "student"

    def __post_init__(self) -> None:
        _require_non_empty("tenant.org_id", self.org_id)
        _require_non_empty("tenant.learning_path_id", self.learning_path_id)
        _require_non_empty("tenant.role", self.role)
        if self.cohort_id is not None:
            _require_non_empty("tenant.cohort_id", self.cohort_id)


@dataclass(frozen=True, slots=True)
class SessionSettings:
    """Learner-facing settings cached in the session record."""

    theme: str = "system"
    locale: str = "en"
    selected_learning_path_id: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty("settings.theme", self.theme)
        _require_non_empty("settings.locale", self.locale)
        if self.selected_learning_path_id is not None:
            _require_non_empty(
                "settings.selected_learning_path_id",
                self.selected_learning_path_id,
            )


@dataclass(frozen=True, slots=True)
class SessionCredential:
    """Optional credential reference or serialized payload attached to a session."""

    reference: str | None = None
    payload: JsonObject = field(default_factory=_empty_json_object)

    def __post_init__(self) -> None:
        if self.reference is not None:
            _require_non_empty("credential.reference", self.reference)
        if not _is_json_object(self.payload):
            msg = "credential.payload must be a JSON object"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Serializable server-side session record stored by opaque session id."""

    session_id: str
    user: SessionUser
    csrf_token: str
    tenant: SessionTenant = field(default_factory=SessionTenant)
    settings: SessionSettings = field(default_factory=SessionSettings)
    tuwel_credentials: SessionCredential | None = None
    tiss_credentials: SessionCredential | None = None
    created_at: str = field(default_factory=lambda: _utc_now_iso())
    updated_at: str = field(default_factory=lambda: _utc_now_iso())

    def __post_init__(self) -> None:
        _require_non_empty("session_id", self.session_id)
        _require_non_empty("csrf_token", self.csrf_token)
        _require_non_empty("created_at", self.created_at)
        _require_non_empty("updated_at", self.updated_at)


@dataclass(frozen=True, slots=True)
class SecretKeySessionManager:
    """Sign with the current key and verify with current plus previous keys."""

    current_key: str
    previous_keys: tuple[str, ...] = ()
    salt: str = SESSION_SALT

    def __post_init__(self) -> None:
        if not self.current_key:
            msg = "current_key must not be empty"
            raise ValueError(msg)

    def sign(self, claims: Mapping[str, str]) -> str:
        return self._serializer(self.current_key).dumps(dict(claims))

    def verify(self, token: str) -> dict[str, str]:
        for secret_key in self._verification_keys():
            try:
                payload = cast("object", self._serializer(secret_key).loads(token))
            except BadData:
                continue
            claims = _coerce_claims(payload)
            if claims is None:
                break
            return claims
        raise InvalidSessionToken

    def _serializer(self, secret_key: str) -> URLSafeSerializer:
        return URLSafeSerializer(secret_key=secret_key, salt=self.salt)

    def _verification_keys(self) -> tuple[str, ...]:
        keys = [self.current_key]
        for previous_key in self.previous_keys:
            if previous_key and previous_key not in keys:
                keys.append(previous_key)
        return tuple(keys)


def create_session_manager(settings: Settings) -> SecretKeySessionManager:
    settings.validate_secret_key_configuration()
    signing_key = settings.session_signing_key()
    previous_keys = tuple(key for key in settings.session_verification_keys() if key != signing_key)
    return SecretKeySessionManager(current_key=signing_key, previous_keys=previous_keys)


def create_session_core(settings: Settings, redis: RedisSessionBackend) -> SessionCore:
    """Create the reusable opaque session core from app settings and Redis."""
    return SessionCore(
        store=RedisSessionStore(redis=redis, ttl_seconds=settings.session_ttl_seconds),
        signer=create_session_manager(settings),
    )


def create_session_record(
    *,
    user: SessionUser,
    tenant: SessionTenant | None = None,
    settings: SessionSettings | None = None,
    tuwel_credentials: SessionCredential | None = None,
    tiss_credentials: SessionCredential | None = None,
) -> SessionRecord:
    """Build a new session record with fresh opaque and CSRF tokens."""
    created_at = _utc_now_iso()
    return SessionRecord(
        session_id=generate_session_id(),
        user=user,
        csrf_token=generate_csrf_token(),
        tenant=tenant or SessionTenant(),
        settings=settings or SessionSettings(),
        tuwel_credentials=tuwel_credentials,
        tiss_credentials=tiss_credentials,
        created_at=created_at,
        updated_at=created_at,
    )


def generate_session_id() -> str:
    """Return a CSPRNG opaque session id suitable for a Redis lookup key."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def generate_csrf_token() -> str:
    """Return a CSPRNG CSRF token stored in the server-side session record."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def sign_session_cookie(session_id: str, signer: SecretKeySessionManager) -> str:
    """Sign an opaque session id for transport in the browser cookie."""
    _require_non_empty("session_id", session_id)
    return signer.sign({SESSION_COOKIE_CLAIM: session_id})


def verify_session_cookie(cookie_value: str, signer: SecretKeySessionManager) -> str:
    """Verify a signed session cookie and return the opaque Redis session id."""
    claims = signer.verify(cookie_value)
    session_id = claims.get(SESSION_COOKIE_CLAIM)
    if not session_id:
        raise InvalidSessionToken
    return session_id


def serialize_session_record(record: SessionRecord) -> JsonObject:
    """Convert a session record to a JSON-compatible mapping for Redis."""
    return {
        "version": SESSION_RECORD_VERSION,
        "session_id": record.session_id,
        "user": {
            "id": record.user.id,
            "display_name": record.user.display_name,
            "email": record.user.email,
        },
        "tenant": {
            "org_id": record.tenant.org_id,
            "learning_path_id": record.tenant.learning_path_id,
            "cohort_id": record.tenant.cohort_id,
            "role": record.tenant.role,
        },
        "csrf_token": record.csrf_token,
        "settings": {
            "theme": record.settings.theme,
            "locale": record.settings.locale,
            "selected_learning_path_id": record.settings.selected_learning_path_id,
        },
        "tuwel_credentials": _serialize_credential(record.tuwel_credentials),
        "tiss_credentials": _serialize_credential(record.tiss_credentials),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def deserialize_session_record(payload: Mapping[str, object]) -> SessionRecord:
    """Validate and convert a JSON mapping into a session record."""
    version = _required_int(payload, "version")
    if version != SESSION_RECORD_VERSION:
        # Records written by an earlier schema are unreadable, not corrupt: callers
        # treat this as a missing session so the learner simply signs in again.
        msg = f"unsupported session record version: {version}"
        raise InvalidSessionToken(msg)

    return SessionRecord(
        session_id=_required_string(payload, "session_id"),
        user=_deserialize_user(_required_mapping(payload, "user")),
        csrf_token=_required_string(payload, "csrf_token"),
        tenant=_deserialize_tenant(_required_mapping(payload, "tenant")),
        settings=_deserialize_settings(_required_mapping(payload, "settings")),
        tuwel_credentials=_deserialize_credential(payload, "tuwel_credentials"),
        tiss_credentials=_deserialize_credential(payload, "tiss_credentials"),
        created_at=_required_string(payload, "created_at"),
        updated_at=_required_string(payload, "updated_at"),
    )


def dumps_session_record(record: SessionRecord) -> str:
    """Serialize a session record to JSON for Redis storage."""
    return json.dumps(serialize_session_record(record))


def loads_session_record(payload: bytes | str) -> SessionRecord:
    """Deserialize a Redis payload into a validated session record.

    Unreadable stored state is reported as an invalid token so callers ask the
    learner to sign in again, rather than failing the request with a 500.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        msg = "session record payload is not valid JSON"
        raise InvalidSessionToken(msg) from exc
    if not isinstance(data, Mapping):
        msg = "session record payload must be a JSON object"
        raise InvalidSessionToken(msg)
    return deserialize_session_record(cast("Mapping[str, object]", data))


@dataclass(slots=True)
class RedisSessionStore:
    """Redis-backed store for opaque session records."""

    redis: RedisSessionBackend
    ttl_seconds: int
    namespace: str = SESSION_KEY_NAMESPACE

    def __post_init__(self) -> None:
        if self.ttl_seconds < 60:
            msg = "ttl_seconds must be at least 60 seconds"
            raise ValueError(msg)
        _require_non_empty("namespace", self.namespace)

    async def create(self, record: SessionRecord, ttl_seconds: int | None = None) -> None:
        """Create or replace a session record with an explicit TTL."""
        await self._set_record(record, ttl_seconds or self.ttl_seconds)

    async def read(self, session_id: str) -> SessionRecord | None:
        """Read a session record by opaque session id."""
        raw_payload = await self.redis.get(self.key_for(session_id))
        if raw_payload is None:
            return None
        return loads_session_record(raw_payload)

    async def save(self, record: SessionRecord) -> bool:
        """Save a session update only when the key still exists with a positive TTL."""
        remaining_ttl = await self.ttl(record.session_id)
        if remaining_ttl <= 0:
            return False
        result = await self.redis.set(
            self.key_for(record.session_id),
            dumps_session_record(record),
            xx=True,
            keepttl=True,
        )
        return bool(result)

    async def refresh(self, session_id: str, ttl_seconds: int | None = None) -> bool:
        """Refresh a session TTL without rewriting the stored record."""
        result = await self.redis.expire(self.key_for(session_id), ttl_seconds or self.ttl_seconds)
        return bool(result)

    async def delete(self, session_id: str) -> bool:
        """Delete a session record by opaque session id."""
        deleted_count = await self.redis.delete(self.key_for(session_id))
        return deleted_count > 0

    async def ttl(self, session_id: str) -> int:
        """Return Redis TTL semantics for a session id."""
        return await self.redis.ttl(self.key_for(session_id))

    def key_for(self, session_id: str) -> str:
        """Return the Redis lookup key for an opaque session id."""
        _require_non_empty("session_id", session_id)
        return f"{self.namespace}:{session_id}"

    async def _set_record(self, record: SessionRecord, ttl_seconds: int) -> None:
        await self.redis.set(
            self.key_for(record.session_id),
            dumps_session_record(record),
            ex=ttl_seconds,
        )


@dataclass(frozen=True, slots=True)
class SessionCore:
    """High-level opaque cookie plus server-side session operations."""

    store: SessionStoreBackend
    signer: SecretKeySessionManager

    async def create(self, record: SessionRecord) -> str:
        """Store a record and return its signed opaque cookie value."""
        await self.store.create(record)
        return sign_session_cookie(record.session_id, self.signer)

    async def read(self, cookie_value: str) -> SessionRecord | None:
        """Verify a cookie and read the matching server-side session."""
        session_id = verify_session_cookie(cookie_value, self.signer)
        return await self.store.read(session_id)

    async def refresh(self, cookie_value: str) -> SessionRecord | None:
        """Refresh the matching server-side session and return its current record."""
        session_id = verify_session_cookie(cookie_value, self.signer)
        record = await self.store.read(session_id)
        if record is None:
            return None
        if not await self.store.refresh(session_id):
            return None
        return record

    async def delete(self, cookie_value: str) -> bool:
        """Verify a cookie and delete the matching server-side session."""
        session_id = verify_session_cookie(cookie_value, self.signer)
        return await self.store.delete(session_id)


def _coerce_claims(payload: object) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None

    payload_items = cast("dict[object, object]", payload).items()
    claims: dict[str, str] = {}
    for key, value in payload_items:
        if not isinstance(key, str) or not isinstance(value, str):
            return None
        claims[key] = value
    return claims


def _serialize_credential(credential: SessionCredential | None) -> JsonValue:
    if credential is None:
        return None
    return {
        "reference": credential.reference,
        "payload": _copy_json_object(credential.payload),
    }


def _deserialize_user(payload: Mapping[str, object]) -> SessionUser:
    return SessionUser(
        id=_required_string(payload, "id"),
        display_name=_optional_string(payload, "display_name") or "",
        email=_optional_string(payload, "email") or "",
    )


def _deserialize_tenant(payload: Mapping[str, object]) -> SessionTenant:
    return SessionTenant(
        org_id=_required_string(payload, "org_id"),
        learning_path_id=_required_string(payload, "learning_path_id"),
        cohort_id=_optional_string(payload, "cohort_id"),
        role=_required_string(payload, "role"),
    )


def _deserialize_settings(payload: Mapping[str, object]) -> SessionSettings:
    return SessionSettings(
        theme=_required_string(payload, "theme"),
        locale=_required_string(payload, "locale"),
        selected_learning_path_id=_optional_string(payload, "selected_learning_path_id"),
    )


def _deserialize_credential(
    payload: Mapping[str, object],
    key: str,
) -> SessionCredential | None:
    credential_payload = payload.get(key)
    if credential_payload is None:
        return None
    credential_mapping = _ensure_mapping(credential_payload, key)
    payload_value = credential_mapping.get("payload", {})
    return SessionCredential(
        reference=_optional_string(credential_mapping, "reference"),
        payload=_coerce_json_object(payload_value, f"{key}.payload"),
    )


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _ensure_mapping(payload.get(key), key)


def _ensure_mapping(value: object, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        msg = f"{key} must be an object"
        raise ValueError(msg)
    return cast("Mapping[str, object]", value)


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        msg = f"{key} must be a non-empty string"
        raise ValueError(msg)
    return value


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{key} must be a string"
        raise ValueError(msg)
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{key} must be an integer"
        raise ValueError(msg)
    return value


def _coerce_json_object(value: object, key: str) -> JsonObject:
    if not _is_json_object(value):
        msg = f"{key} must be a JSON object"
        raise ValueError(msg)
    return _copy_json_object(value)


def _copy_json_object(payload: Mapping[str, JsonValue]) -> JsonObject:
    return {key: _copy_json_value(value) for key, value in payload.items()}


def _copy_json_value(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [_copy_json_value(item) for item in value]
    if isinstance(value, dict):
        return _copy_json_object(value)
    return value


def _is_json_object(value: object) -> TypeGuard[JsonObject]:
    if not isinstance(value, dict):
        return False
    items = cast("dict[object, object]", value).items()
    return all(isinstance(key, str) and _is_json_value(item) for key, item in items)


def _is_json_value(value: object) -> TypeGuard[JsonValue]:
    if value is None or isinstance(value, str | bool):
        return True
    if isinstance(value, int):
        return not isinstance(value, bool)
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        items = cast("list[object]", value)
        return all(_is_json_value(item) for item in items)
    return _is_json_object(value)


def _require_non_empty(name: str, value: str) -> None:
    if not value:
        msg = f"{name} must not be empty"
        raise ValueError(msg)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
