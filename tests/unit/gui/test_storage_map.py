"""Tests for storage_map constant completeness."""

from __future__ import annotations

from sophia.gui.state.storage_map import (
    TIER_MAP,
    USER_QUICKSTART_COMPLETED,
    USER_QUICKSTART_SELECTED_COURSES,
    USER_QUICKSTART_SKIPPED,
)


class TestQuickstartStorageKeys:
    """Quickstart keys exist and are registered in TIER_MAP."""

    def test_selected_courses_constant_value(self) -> None:
        assert USER_QUICKSTART_SELECTED_COURSES == "quickstart_selected_courses"

    def test_quickstart_completed_in_tier_map(self) -> None:
        assert USER_QUICKSTART_COMPLETED in TIER_MAP["user"]

    def test_selected_courses_in_tier_map(self) -> None:
        assert USER_QUICKSTART_SELECTED_COURSES in TIER_MAP["user"]

    def test_quickstart_skipped_constant_value(self) -> None:
        assert USER_QUICKSTART_SKIPPED == "quickstart_skipped"

    def test_quickstart_skipped_in_tier_map(self) -> None:
        assert USER_QUICKSTART_SKIPPED in TIER_MAP["user"]

    def test_session_count_not_in_storage_map(self) -> None:
        """USER_SESSION_COUNT was dead code and should be removed."""
        import sophia.gui.state.storage_map as sm

        assert not hasattr(sm, "USER_SESSION_COUNT")
