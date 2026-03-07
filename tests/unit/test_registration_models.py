"""Tests for Kairos registration domain models."""

from __future__ import annotations

from sophia.domain.models import (
    RegistrationGroup,
    RegistrationResult,
    RegistrationStatus,
    RegistrationTarget,
    RegistrationType,
)


class TestRegistrationEnums:
    def test_status_values(self):
        assert RegistrationStatus.PENDING == "pending"
        assert RegistrationStatus.OPEN == "open"
        assert RegistrationStatus.REGISTERED == "registered"
        assert RegistrationStatus.FULL == "full"
        assert RegistrationStatus.CLOSED == "closed"
        assert RegistrationStatus.FAILED == "failed"

    def test_type_values(self):
        assert RegistrationType.LVA == "lva"
        assert RegistrationType.GROUP == "group"
        assert RegistrationType.EXAM == "exam"


class TestRegistrationGroup:
    def test_defaults(self):
        g = RegistrationGroup(group_id="g1", name="Group 1")
        assert g.capacity == 0
        assert g.enrolled == 0
        assert g.status == RegistrationStatus.PENDING

    def test_full_construction(self):
        g = RegistrationGroup(
            group_id="g1",
            name="Group 1",
            day="Monday",
            time_start="09:00",
            time_end="11:00",
            location="Room A",
            capacity=30,
            enrolled=25,
            status=RegistrationStatus.OPEN,
            register_button_id="form:btn0",
        )
        assert g.capacity == 30
        assert g.time_start == "09:00"


class TestRegistrationTarget:
    def test_defaults(self):
        t = RegistrationTarget(
            course_number="186.813",
            semester="2026S",
            registration_type=RegistrationType.LVA,
        )
        assert t.status == RegistrationStatus.PENDING
        assert t.groups == []
        assert t.preferred_group_ids == []

    def test_with_groups(self):
        g = RegistrationGroup(group_id="g1", name="G1")
        t = RegistrationTarget(
            course_number="186.813",
            semester="2026S",
            registration_type=RegistrationType.GROUP,
            groups=[g],
            preferred_group_ids=["g1"],
        )
        assert len(t.groups) == 1


class TestRegistrationResult:
    def test_success(self):
        r = RegistrationResult(
            course_number="186.813",
            registration_type=RegistrationType.LVA,
            success=True,
            message="OK",
        )
        assert r.success

    def test_failure(self):
        r = RegistrationResult(
            course_number="186.813",
            registration_type=RegistrationType.GROUP,
            success=False,
            message="Full",
        )
        assert not r.success
