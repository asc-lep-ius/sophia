"""TOTP generation and the spent-step ledger."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sophia.adapters.totp import (
    InvalidTotpSecretError,
    StepLedger,
    code_for_step,
    fresh_code,
    ledger_path,
    matching_step,
    normalize_secret,
    step_at,
)

if TYPE_CHECKING:
    from pathlib import Path

# RFC 6238 Appendix B: the ASCII secret "12345678901234567890", base32-encoded.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_codes_match_the_rfc_6238_sha1_vectors(timestamp: int, expected: str) -> None:
    assert code_for_step(RFC_SECRET, step_at(timestamp), digits=8) == expected


def test_six_digit_code_is_the_low_digits_of_the_rfc_value() -> None:
    assert code_for_step(RFC_SECRET, step_at(59)) == "287082"


@pytest.mark.parametrize(
    "raw",
    [
        "gezd gnbv gy3t qojq gezd gnbv gy3t qojq",
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ====",
    ],
)
def test_secret_is_normalized_from_authenticator_formats(raw: str) -> None:
    assert normalize_secret(raw) == RFC_SECRET


@pytest.mark.parametrize("raw", ["", "   ", "not-base32!", "GEZDG1"])
def test_secret_that_is_not_base32_is_refused(raw: str) -> None:
    with pytest.raises(InvalidTotpSecretError):
        normalize_secret(raw)


def test_matching_step_accepts_one_step_of_clock_skew() -> None:
    previous_step_code = code_for_step(RFC_SECRET, step_at(1_000_000) - 1)
    assert matching_step(RFC_SECRET, previous_step_code, 1_000_000) == step_at(1_000_000) - 1
    assert matching_step(RFC_SECRET, "000000", 1_000_000) is None


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_fresh_code_uses_the_current_step_and_records_it(tmp_path: Path) -> None:
    clock = FakeClock(1_000_000.0)
    ledger = StepLedger(ledger_path(tmp_path))

    code = await fresh_code(RFC_SECRET, ledger, clock=clock, sleep=clock.sleep)

    assert code == code_for_step(RFC_SECRET, step_at(1_000_000))
    assert ledger.last_used() == step_at(1_000_000)
    assert clock.slept == []


async def test_fresh_code_waits_for_the_next_step_when_this_one_is_spent(tmp_path: Path) -> None:
    """The IdP accepts each code once; reusing a spent step burns a failed attempt."""
    clock = FakeClock(1_000_005.0)
    ledger = StepLedger(ledger_path(tmp_path))
    spent = step_at(clock.now)
    ledger.record(spent)

    code = await fresh_code(RFC_SECRET, ledger, clock=clock, sleep=clock.sleep)

    assert clock.slept, "it should have waited for the next step"
    assert step_at(clock.now) == spent + 1
    assert code == code_for_step(RFC_SECRET, spent + 1)
    assert ledger.last_used() == spent + 1


async def test_ledger_survives_across_processes(tmp_path: Path) -> None:
    StepLedger(ledger_path(tmp_path)).record(42)
    assert StepLedger(ledger_path(tmp_path)).last_used() == 42
    assert (ledger_path(tmp_path).stat().st_mode & 0o777) == 0o600


def test_unreadable_ledger_counts_as_nothing_spent(tmp_path: Path) -> None:
    ledger_path(tmp_path).write_text("not json")
    assert StepLedger(ledger_path(tmp_path)).last_used() is None


async def test_a_ledger_step_from_the_future_does_not_hold_the_login(tmp_path: Path) -> None:
    """After the clock moves back, waiting for a 'spent' future step would block for hours."""
    clock = FakeClock(1_000_000.0)
    ledger = StepLedger(ledger_path(tmp_path))
    ledger.record(step_at(clock.now) + 500)

    code = await fresh_code(RFC_SECRET, ledger, clock=clock, sleep=clock.sleep)

    assert clock.slept == []
    assert code == code_for_step(RFC_SECRET, step_at(1_000_000))
