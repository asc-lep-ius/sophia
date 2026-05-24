"""Secret-key session signing stubs for the backend API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from itsdangerous import BadData, URLSafeSerializer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sophia.config import Settings

SESSION_SALT = "sophia.api.session"


class InvalidSessionToken(ValueError):
    """Raised when a session token cannot be verified."""


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
