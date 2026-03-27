"""Tests for the Chronos deadlines page — pure helpers and constants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# format_due_date
# ---------------------------------------------------------------------------


class TestFormatDueDate:
    @pytest.mark.parametrize(
        ("delta_days", "expected_contains"),
        [
            (3, "in 3 days"),
            (1, "in 1 day"),
            (0, "today"),
            (-1, "overdue by 1 day"),
            (-5, "overdue by 5 days"),
        ],
    )
    def test_relative_formatting(self, delta_days: int, expected_contains: str) -> None:
        from sophia.gui.pages.chronos import format_due_date

        now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
        due = now + timedelta(days=delta_days)
        result = format_due_date(due, now=now)
        assert expected_contains in result

    def test_defaults_to_utcnow_when_now_omitted(self) -> None:
        from sophia.gui.pages.chronos import format_due_date

        far_future = datetime(2099, 1, 1, tzinfo=UTC)
        result = format_due_date(far_future)
        assert "in" in result

    def test_large_overdue(self) -> None:
        from sophia.gui.pages.chronos import format_due_date

        now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
        due = now - timedelta(days=30)
        result = format_due_date(due, now=now)
        assert "overdue by 30 days" in result


# ---------------------------------------------------------------------------
# format_hours
# ---------------------------------------------------------------------------


class TestFormatHours:
    @pytest.mark.parametrize(
        ("hours", "expected"),
        [
            (0, "0min"),
            (0.5, "30min"),
            (1.0, "1.0h"),
            (1.5, "1.5h"),
            (2.25, "2.2h"),
        ],
    )
    def test_formats_correctly(self, hours: float, expected: str) -> None:
        from sophia.gui.pages.chronos import format_hours

        assert format_hours(hours) == expected

    def test_small_fractional_shows_minutes(self) -> None:
        from sophia.gui.pages.chronos import format_hours

        assert format_hours(0.25) == "15min"

    def test_exactly_one_hour(self) -> None:
        from sophia.gui.pages.chronos import format_hours

        assert format_hours(1.0) == "1.0h"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestDeadlineTypeColors:
    def test_has_all_types(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert len(_DEADLINE_TYPE_COLORS) == 5

    def test_assignment_is_green(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["assignment"] == "green"

    def test_quiz_is_blue(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["quiz"] == "blue"

    def test_exam_is_red(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["exam"] == "red"

    def test_exam_registration_is_orange(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["exam_registration"] == "orange"

    def test_checkmark_is_teal(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["checkmark"] == "teal"


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_chronos_content_callable(self) -> None:
        from sophia.gui.pages.chronos import chronos_content

        assert callable(chronos_content)

    def test_format_due_date_callable(self) -> None:
        from sophia.gui.pages.chronos import format_due_date

        assert callable(format_due_date)

    def test_format_hours_callable(self) -> None:
        from sophia.gui.pages.chronos import format_hours

        assert callable(format_hours)


# ---------------------------------------------------------------------------
# Storage accessors — RuntimeError guards
# ---------------------------------------------------------------------------


class TestStorageAccessors:
    """Verify that storage accessors return safe defaults outside a NiceGUI request context."""

    @pytest.mark.parametrize(
        ("accessor", "expected_default"),
        [
            ("_get_course_filter", None),
            ("_get_active_timer", ""),
            ("_get_estimate_draft", {}),
        ],
    )
    def test_tab_getter_returns_default_on_runtime_error(
        self,
        accessor: str,
        expected_default: object,
    ) -> None:
        from unittest.mock import PropertyMock, patch

        import sophia.gui.pages.chronos as mod

        mock_tab = PropertyMock(side_effect=RuntimeError)
        with patch.object(type(mod.app.storage), "tab", mock_tab):
            result = getattr(mod, accessor)()
        assert result == expected_default

    def test_get_current_course_returns_zero_on_runtime_error(self) -> None:
        from unittest.mock import PropertyMock, patch

        import sophia.gui.pages.chronos as mod

        mock_user = PropertyMock(side_effect=RuntimeError)
        with patch.object(type(mod.app.storage), "user", mock_user):
            result = mod._get_current_course()
        assert result == 0

    @pytest.mark.parametrize(
        ("setter", "arg"),
        [
            ("_set_course_filter", 42),
            ("_set_active_timer", "abc"),
            ("_set_estimate_draft", {"key": "val"}),
        ],
    )
    def test_setter_logs_debug_on_runtime_error(
        self,
        setter: str,
        arg: object,
    ) -> None:
        from unittest.mock import PropertyMock, patch

        import sophia.gui.pages.chronos as mod

        mock_tab = PropertyMock(side_effect=RuntimeError)
        with (
            patch.object(type(mod.app.storage), "tab", mock_tab),
            patch.object(mod.log, "debug") as mock_debug,
        ):
            getattr(mod, setter)(arg)  # must not raise
        mock_debug.assert_called_once()


# ---------------------------------------------------------------------------
# sync_deadlines_from_gui wrapper
# ---------------------------------------------------------------------------


class TestSyncButton:
    """Verify sync_deadlines_from_gui wrapper handles errors gracefully."""

    @pytest.mark.asyncio
    async def test_sync_wrapper_returns_empty_on_auth_error(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from sophia.domain.errors import AuthError
        from sophia.gui.services.chronos_service import sync_deadlines_from_gui

        mock_app = MagicMock()
        with patch(
            "sophia.gui.services.chronos_service._sync_deadlines",
            new_callable=AsyncMock,
        ) as mock_sync:
            mock_sync.side_effect = AuthError("expired")
            result = await sync_deadlines_from_gui(mock_app)
            assert result == []

    @pytest.mark.asyncio
    async def test_sync_wrapper_returns_empty_on_general_error(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from sophia.gui.services.chronos_service import sync_deadlines_from_gui

        mock_app = MagicMock()
        with patch(
            "sophia.gui.services.chronos_service._sync_deadlines",
            new_callable=AsyncMock,
        ) as mock_sync:
            mock_sync.side_effect = RuntimeError("connection failed")
            result = await sync_deadlines_from_gui(mock_app)
            assert result == []

    @pytest.mark.asyncio
    async def test_sync_wrapper_returns_deadlines_on_success(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from sophia.gui.services.chronos_service import sync_deadlines_from_gui

        mock_app = MagicMock()
        mock_deadlines = [MagicMock(), MagicMock()]
        with patch(
            "sophia.gui.services.chronos_service._sync_deadlines",
            new_callable=AsyncMock,
        ) as mock_sync:
            mock_sync.return_value = mock_deadlines
            result = await sync_deadlines_from_gui(mock_app)
            assert result == mock_deadlines
            mock_sync.assert_called_once_with(mock_app)


# ---------------------------------------------------------------------------
# Chronos empty state — source inspection
# ---------------------------------------------------------------------------


class TestChronosEmptyState:
    """Verify Chronos empty state shows pedagogical guidance."""

    def test_empty_state_text_constants(self) -> None:
        import inspect

        from sophia.gui.pages.chronos import _deadline_list

        # NiceGUI @refreshable wraps the function; access via .func
        func = getattr(_deadline_list, "func", _deadline_list)
        source = inspect.getsource(func)
        assert "No deadlines synced" in source
        assert "predict" in source.lower()
        assert "Sync from TUWEL" in source
