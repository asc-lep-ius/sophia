"""Tests for Kairos registration service."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sophia.domain.errors import RegistrationError
from sophia.domain.models import (
    RegistrationGroup,
    RegistrationResult,
    RegistrationStatus,
    RegistrationTarget,
    RegistrationType,
)
from sophia.services.registration import (
    _calculate_wait,  # pyright: ignore[reportPrivateUsage]
    register_with_preferences,
    watch_and_register,
)


class FakeRegistrationProvider:
    """Test double for RegistrationProvider protocol."""

    def __init__(
        self,
        register_results: dict[str | None, RegistrationResult] | None = None,
        status: RegistrationTarget | None = None,
        groups: list[RegistrationGroup] | None = None,
        status_sequence: list[RegistrationTarget] | None = None,
    ) -> None:
        self._register_results = register_results or {}
        self._status = status
        self._groups = groups or []
        self._status_sequence = status_sequence or []
        self._status_call_count = 0
        self.register_calls: list[tuple[str, str, str | None]] = []

    async def get_registration_status(
        self, course_number: str, semester: str
    ) -> RegistrationTarget:
        if self._status_sequence:
            idx = min(self._status_call_count, len(self._status_sequence) - 1)
            self._status_call_count += 1
            return self._status_sequence[idx]
        if self._status:
            return self._status
        return RegistrationTarget(
            course_number=course_number,
            semester=semester,
            registration_type=RegistrationType.LVA,
        )

    async def get_groups(
        self, course_number: str, semester: str
    ) -> list[RegistrationGroup]:
        return self._groups

    async def register(
        self, course_number: str, semester: str, group_id: str | None = None
    ) -> RegistrationResult:
        self.register_calls.append((course_number, semester, group_id))
        if group_id in self._register_results:
            return self._register_results[group_id]
        if None in self._register_results:
            return self._register_results[None]
        return RegistrationResult(
            course_number=course_number,
            registration_type=RegistrationType.GROUP,
            success=False,
            message="Not configured",
            attempted_at=datetime.now(UTC).isoformat(),
        )


def _ok(group: str = "") -> RegistrationResult:
    return RegistrationResult(
        course_number="186.813",
        registration_type=RegistrationType.GROUP,
        success=True,
        group_name=group,
        message="OK",
        attempted_at=datetime.now(UTC).isoformat(),
    )


def _fail(msg: str = "Full") -> RegistrationResult:
    return RegistrationResult(
        course_number="186.813",
        registration_type=RegistrationType.GROUP,
        success=False,
        message=msg,
        attempted_at=datetime.now(UTC).isoformat(),
    )


class TestRegisterWithPreferences:
    async def test_lva_registration_no_groups(self):
        provider = FakeRegistrationProvider(register_results={None: _ok()})
        result = await register_with_preferences(provider, "186.813", "2026S", [])
        assert result.success
        assert provider.register_calls == [("186.813", "2026S", None)]

    async def test_first_group_succeeds(self):
        provider = FakeRegistrationProvider(
            register_results={
                "g1": _ok("Group 1"),
                "g2": _ok("Group 2"),
            }
        )
        result = await register_with_preferences(provider, "186.813", "2026S", ["g1", "g2"])
        assert result.success
        assert result.group_name == "Group 1"
        assert len(provider.register_calls) == 1

    async def test_fallback_to_second_group(self):
        provider = FakeRegistrationProvider(
            register_results={
                "g1": _fail(),
                "g2": _ok("Group 2"),
            }
        )
        result = await register_with_preferences(provider, "186.813", "2026S", ["g1", "g2"])
        assert result.success
        assert result.group_name == "Group 2"
        assert len(provider.register_calls) == 2

    async def test_all_groups_fail(self):
        provider = FakeRegistrationProvider(
            register_results={
                "g1": _fail("Full"),
                "g2": _fail("Full"),
            }
        )
        result = await register_with_preferences(provider, "186.813", "2026S", ["g1", "g2"])
        assert not result.success

    async def test_preserves_preference_order(self):
        provider = FakeRegistrationProvider(
            register_results={
                "g3": _fail(),
                "g1": _fail(),
                "g2": _ok("Group 2"),
            }
        )
        result = await register_with_preferences(
            provider, "186.813", "2026S", ["g3", "g1", "g2"]
        )
        assert result.success
        assert provider.register_calls == [
            ("186.813", "2026S", "g3"),
            ("186.813", "2026S", "g1"),
            ("186.813", "2026S", "g2"),
        ]


class TestWatchAndRegister:
    async def test_already_registered(self):
        provider = FakeRegistrationProvider(
            status=RegistrationTarget(
                course_number="186.813",
                semester="2026S",
                registration_type=RegistrationType.LVA,
                status=RegistrationStatus.REGISTERED,
            ),
        )
        result = await watch_and_register(provider, "186.813", "2026S", [])
        assert result.success
        assert "Already registered" in result.message

    async def test_open_registers_immediately(self):
        provider = FakeRegistrationProvider(
            status=RegistrationTarget(
                course_number="186.813",
                semester="2026S",
                registration_type=RegistrationType.LVA,
                status=RegistrationStatus.OPEN,
            ),
            register_results={None: _ok()},
        )
        result = await watch_and_register(provider, "186.813", "2026S", [])
        assert result.success

    async def test_closed_raises(self):
        provider = FakeRegistrationProvider(
            status=RegistrationTarget(
                course_number="186.813",
                semester="2026S",
                registration_type=RegistrationType.LVA,
                status=RegistrationStatus.CLOSED,
            ),
        )
        with pytest.raises(RegistrationError, match="closed"):
            await watch_and_register(provider, "186.813", "2026S", [])

    async def test_pending_then_open(self):
        """Simulates status changing from PENDING to OPEN."""
        provider = FakeRegistrationProvider(
            status_sequence=[
                RegistrationTarget(
                    course_number="186.813",
                    semester="2026S",
                    registration_type=RegistrationType.LVA,
                    status=RegistrationStatus.PENDING,
                ),
                RegistrationTarget(
                    course_number="186.813",
                    semester="2026S",
                    registration_type=RegistrationType.LVA,
                    status=RegistrationStatus.OPEN,
                ),
            ],
            register_results={None: _ok()},
        )
        result = await watch_and_register(provider, "186.813", "2026S", [])
        assert result.success


class TestCalculateWait:
    def test_no_start_time_returns_default(self):
        target = RegistrationTarget(
            course_number="186.813",
            semester="2026S",
            registration_type=RegistrationType.LVA,
        )
        wait = _calculate_wait(target, lead_time_secs=60.0)
        assert wait == 2.0

    def test_invalid_date_returns_default(self):
        target = RegistrationTarget(
            course_number="186.813",
            semester="2026S",
            registration_type=RegistrationType.LVA,
            registration_start="invalid-date",
        )
        wait = _calculate_wait(target, lead_time_secs=60.0)
        assert wait == 2.0

    def test_future_date_returns_capped_wait(self):
        target = RegistrationTarget(
            course_number="186.813",
            semester="2026S",
            registration_type=RegistrationType.LVA,
            registration_start="01.01.2099 08:00",
        )
        wait = _calculate_wait(target, lead_time_secs=60.0)
        assert wait == 300.0
