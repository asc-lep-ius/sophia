"""TOTP codes (RFC 6238) for logging in to the TU Wien IdP without a person.

MFA has been mandatory since 2026-04-01, so a session that dies can only come
back with a code. The learner's authenticator secret, held in the keyring,
generates one. Standard library only: the algorithm is a dozen lines, and the
RFC's own test vectors pin it.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import struct
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

log = structlog.get_logger()

STEP_SECONDS = 30
DIGITS = 6
_LEDGER_FILENAME = "totp_last_step.json"
# Past the step boundary, so a clock a little behind the IdP's still lands in
# the new step.
_STEP_MARGIN_SECONDS = 1.0


class InvalidTotpSecretError(ValueError):
    """The secret is not base32, so it cannot be an authenticator's secret."""


def normalize_secret(raw: str) -> str:
    """Strip spaces and padding, upper-case, and reject anything not base32."""
    secret = "".join(raw.split()).upper().rstrip("=")
    if not secret:
        raise InvalidTotpSecretError("TOTP secret is empty")
    try:
        _decode(secret)
    except (binascii.Error, ValueError) as exc:
        raise InvalidTotpSecretError("TOTP secret is not valid base32") from exc
    return secret


def step_at(timestamp: float) -> int:
    return int(timestamp // STEP_SECONDS)


def code_for_step(secret: str, step: int, digits: int = DIGITS) -> str:
    digest = hmac.new(_decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def matching_step(secret: str, code: str, timestamp: float, window: int = 1) -> int | None:
    """The step within ``window`` steps of ``timestamp`` whose code is ``code``."""
    current = step_at(timestamp)
    for step in range(current - window, current + window + 1):
        if hmac.compare_digest(code_for_step(secret, step), code):
            return step
    return None


def _decode(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def ledger_path(config_dir: Path) -> Path:
    return config_dir / _LEDGER_FILENAME


@dataclass(frozen=True)
class StepLedger:
    """The last TOTP step a login on this box spent.

    The IdP accepts each code once, so a re-login in the same 30 s step as the
    login before it would burn a failed attempt. A file rather than memory,
    because the CLI login, SESSION_CMD and the API are three processes.
    """

    path: Path

    def last_used(self) -> int | None:
        try:
            value = json.loads(self.path.read_text())["step"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return value if isinstance(value, int) else None

    def record(self, step: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"step": step}))
        self.path.chmod(0o600)


async def fresh_code(
    secret: str,
    ledger: StepLedger,
    *,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """A code from a step no earlier login has spent, waiting for one if needed."""
    last = ledger.last_used()
    if last is not None and last > step_at(clock()) + 1:
        # A step from the future means the clock moved back since it was
        # recorded. Waiting for it would hold the re-login lock for as long.
        log.warning("totp.ledger_ahead_of_clock", steps_ahead=last - step_at(clock()))
        last = None
    while last is not None and step_at(clock()) <= last:
        wait = (last + 1) * STEP_SECONDS - clock() + _STEP_MARGIN_SECONDS
        log.info("totp.waiting_for_unspent_step", seconds=round(wait, 1))
        await sleep(max(wait, 0.0))
    step = step_at(clock())
    ledger.record(step)
    return code_for_step(secret, step)
