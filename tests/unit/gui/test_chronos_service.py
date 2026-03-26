"""Tests for GUI chronos service wrappers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from sophia.domain.models import (
    CalibrationMetrics,
    Deadline,
    DeadlineType,
    EffortEstimate,
    EstimationScaffold,
)

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

COURSE_ID = 42
DEADLINE_ID = "dl-abc-123"

_PATCH_BASE = "sophia.gui.services.chronos_service"


def _make_deadline(**overrides: Any) -> Deadline:
    defaults = {
        "id": DEADLINE_ID,
        "name": "HW 1",
        "course_id": COURSE_ID,
        "course_name": "Algorithms",
        "deadline_type": DeadlineType.ASSIGNMENT,
        "due_at": datetime.now(UTC) + timedelta(days=3),
    }
    defaults.update(overrides)
    return Deadline(**defaults)  # type: ignore[arg-type]


def _make_estimate(**overrides: Any) -> EffortEstimate:
    defaults = {
        "deadline_id": DEADLINE_ID,
        "course_id": COURSE_ID,
        "predicted_hours": 3.0,
        "scaffold_level": EstimationScaffold.FULL,
        "estimated_at": "2026-01-01T00:00:00",
    }
    defaults.update(overrides)
    return EffortEstimate(**defaults)  # type: ignore[arg-type]


# -- get_upcoming_deadlines --------------------------------------------------


class TestGetUpcomingDeadlines:
    @pytest.mark.asyncio
    async def test_returns_deadlines(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_upcoming_deadlines

        expected = [_make_deadline()]
        with patch(
            f"{_PATCH_BASE}._get_deadlines",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fn:
            result = await get_upcoming_deadlines(mock_container)

        assert result == expected
        mock_fn.assert_awaited_once_with(mock_container.db, course_id=None, horizon_days=14)

    @pytest.mark.asyncio
    async def test_passes_optional_params(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_upcoming_deadlines

        with patch(
            f"{_PATCH_BASE}._get_deadlines",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fn:
            await get_upcoming_deadlines(mock_container, course_id=COURSE_ID, horizon_days=7)

        mock_fn.assert_awaited_once_with(mock_container.db, course_id=COURSE_ID, horizon_days=7)

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_upcoming_deadlines

        with patch(
            f"{_PATCH_BASE}._get_deadlines",
            new_callable=AsyncMock,
            side_effect=Exception("db down"),
        ):
            result = await get_upcoming_deadlines(mock_container)

        assert result == []


# -- get_deadline_priority ---------------------------------------------------


class TestGetDeadlinePriority:
    @pytest.mark.asyncio
    async def test_returns_priority_dict(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_priority

        deadline = _make_deadline()
        expected_score = {
            "urgency": 0.5,
            "importance": 0.3,
            "effort_gap": 1.0,
            "score": 0.15,
            "confidence_multiplier": 1.0,
        }
        with (
            patch(
                f"{_PATCH_BASE}._get_tracked_time",
                new_callable=AsyncMock,
                return_value=1.5,
            ),
            patch(
                f"{_PATCH_BASE}._compute_priority_score",
                return_value=expected_score,
            ) as mock_score,
        ):
            result = await get_deadline_priority(deadline, mock_container)

        assert result == expected_score
        mock_score.assert_called_once_with(deadline, None, 1.5)

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_priority

        deadline = _make_deadline()
        with patch(
            f"{_PATCH_BASE}._get_tracked_time",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await get_deadline_priority(deadline, mock_container)

        assert result == {}


# -- estimate_effort ---------------------------------------------------------


class TestEstimateEffort:
    @pytest.mark.asyncio
    async def test_returns_estimate(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import estimate_effort

        expected = _make_estimate()
        with patch(
            f"{_PATCH_BASE}._record_estimate",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fn:
            result = await estimate_effort(
                mock_container,
                deadline_id=DEADLINE_ID,
                course_id=COURSE_ID,
                predicted_hours=3.0,
            )

        assert result == expected
        # Must pass app directly, not app.db
        mock_fn.assert_awaited_once_with(
            mock_container,
            deadline_id=DEADLINE_ID,
            course_id=COURSE_ID,
            predicted_hours=3.0,
            breakdown=None,
            intention=None,
        )

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import estimate_effort

        with patch(
            f"{_PATCH_BASE}._record_estimate",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await estimate_effort(
                mock_container,
                deadline_id=DEADLINE_ID,
                course_id=COURSE_ID,
                predicted_hours=3.0,
            )

        assert result is None


# -- start_deadline_timer ----------------------------------------------------


class TestStartDeadlineTimer:
    @pytest.mark.asyncio
    async def test_calls_start_timer(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import start_deadline_timer

        with patch(
            f"{_PATCH_BASE}._start_timer",
            new_callable=AsyncMock,
        ) as mock_fn:
            await start_deadline_timer(mock_container, DEADLINE_ID)

        mock_fn.assert_awaited_once_with(mock_container.db, DEADLINE_ID)

    @pytest.mark.asyncio
    async def test_swallows_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import start_deadline_timer

        with patch(
            f"{_PATCH_BASE}._start_timer",
            new_callable=AsyncMock,
            side_effect=Exception("already running"),
        ):
            await start_deadline_timer(mock_container, DEADLINE_ID)


# -- stop_deadline_timer -----------------------------------------------------


class TestStopDeadlineTimer:
    @pytest.mark.asyncio
    async def test_returns_elapsed(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import stop_deadline_timer

        with patch(
            f"{_PATCH_BASE}._stop_timer",
            new_callable=AsyncMock,
            return_value=1.5,
        ):
            result = await stop_deadline_timer(mock_container, DEADLINE_ID)

        assert result == 1.5

    @pytest.mark.asyncio
    async def test_returns_zero_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import stop_deadline_timer

        with patch(
            f"{_PATCH_BASE}._stop_timer",
            new_callable=AsyncMock,
            side_effect=Exception("no timer"),
        ):
            result = await stop_deadline_timer(mock_container, DEADLINE_ID)

        assert result == 0.0


# -- get_deadline_tracked_time -----------------------------------------------


class TestGetDeadlineTrackedTime:
    @pytest.mark.asyncio
    async def test_returns_hours(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_tracked_time

        with patch(
            f"{_PATCH_BASE}._get_tracked_time",
            new_callable=AsyncMock,
            return_value=4.5,
        ):
            result = await get_deadline_tracked_time(mock_container, DEADLINE_ID)

        assert result == 4.5

    @pytest.mark.asyncio
    async def test_returns_zero_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_tracked_time

        with patch(
            f"{_PATCH_BASE}._get_tracked_time",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await get_deadline_tracked_time(mock_container, DEADLINE_ID)

        assert result == 0.0


# -- reflect_on_deadline -----------------------------------------------------


class TestReflectOnDeadline:
    @pytest.mark.asyncio
    async def test_calls_record_reflection(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import reflect_on_deadline

        with patch(
            f"{_PATCH_BASE}._record_reflection",
            new_callable=AsyncMock,
        ) as mock_fn:
            await reflect_on_deadline(
                mock_container,
                DEADLINE_ID,
                predicted_hours=3.0,
                actual_hours=5.0,
                reflection_text="Took longer than expected.",
            )

        mock_fn.assert_awaited_once_with(
            mock_container.db,
            DEADLINE_ID,
            predicted_hours=3.0,
            actual_hours=5.0,
            reflection_text="Took longer than expected.",
        )

    @pytest.mark.asyncio
    async def test_swallows_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import reflect_on_deadline

        with patch(
            f"{_PATCH_BASE}._record_reflection",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            await reflect_on_deadline(
                mock_container,
                DEADLINE_ID,
                predicted_hours=3.0,
                actual_hours=5.0,
                reflection_text="Took longer.",
            )


# -- get_deadline_scaffold ---------------------------------------------------


class TestGetDeadlineScaffold:
    @pytest.mark.asyncio
    async def test_returns_scaffold(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_scaffold

        with patch(
            f"{_PATCH_BASE}._get_scaffold_level",
            new_callable=AsyncMock,
            return_value=EstimationScaffold.MINIMAL,
        ) as mock_fn:
            result = await get_deadline_scaffold(mock_container, DeadlineType.ASSIGNMENT)

        assert result is EstimationScaffold.MINIMAL
        mock_fn.assert_awaited_once_with(mock_container.db, DeadlineType.ASSIGNMENT, course_id=None)

    @pytest.mark.asyncio
    async def test_returns_full_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_scaffold

        with patch(
            f"{_PATCH_BASE}._get_scaffold_level",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await get_deadline_scaffold(mock_container, DeadlineType.ASSIGNMENT)

        assert result is EstimationScaffold.FULL


# -- format_deadline_feedback ------------------------------------------------


class TestFormatDeadlineFeedback:
    def test_wraps_sync_function(self) -> None:
        from sophia.gui.services.chronos_service import format_deadline_feedback

        with patch(
            f"{_PATCH_BASE}._format_estimation_feedback",
            return_value="✅ Well calibrated!",
        ) as mock_fn:
            result = format_deadline_feedback(3.0, 3.2)

        assert result == "✅ Well calibrated!"
        mock_fn.assert_called_once_with(3.0, 3.2)

    def test_with_none_predicted(self) -> None:
        from sophia.gui.services.chronos_service import format_deadline_feedback

        with patch(
            f"{_PATCH_BASE}._format_estimation_feedback",
            return_value="📊 Tracked 2.0h total",
        ):
            result = format_deadline_feedback(None, 2.0)

        assert "Tracked" in result


# -- get_deadline_calibration ------------------------------------------------


class TestGetDeadlineCalibration:
    @pytest.mark.asyncio
    async def test_returns_metrics(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_calibration

        expected = [
            CalibrationMetrics(
                domain="effort:assignment",
                sample_count=5,
                mean_error=-0.5,
                mean_absolute_error=0.7,
                trend="improving",
            )
        ]
        with patch(
            f"{_PATCH_BASE}._get_calibration_metrics",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            result = await get_deadline_calibration(mock_container)

        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_calibration

        with patch(
            f"{_PATCH_BASE}._get_calibration_metrics",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await get_deadline_calibration(mock_container)

        assert result == []
