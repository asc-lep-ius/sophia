"""Tests for GUI chronos service wrappers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from sophia.domain.errors import AuthError
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


# -- mark_deadline_complete --------------------------------------------------


class TestMarkDeadlineComplete:
    @pytest.mark.asyncio
    async def test_returns_predicted_actual_feedback(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import mark_deadline_complete

        with patch(
            f"{_PATCH_BASE}._complete_deadline",
            new_callable=AsyncMock,
            return_value=(3.0, 4.5, "feedback text"),
        ) as mock_fn:
            predicted, actual, feedback = await mark_deadline_complete(mock_container, DEADLINE_ID)

        assert predicted == 3.0
        assert actual == 4.5
        assert feedback == "feedback text"
        mock_fn.assert_awaited_once_with(mock_container, DEADLINE_ID)

    @pytest.mark.asyncio
    async def test_returns_safe_defaults_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import mark_deadline_complete

        with patch(
            f"{_PATCH_BASE}._complete_deadline",
            new_callable=AsyncMock,
            side_effect=Exception("db down"),
        ):
            predicted, actual, feedback = await mark_deadline_complete(mock_container, DEADLINE_ID)

        assert predicted is None
        assert actual == 0.0
        assert feedback == ""


# -- SyncResult dataclass ---------------------------------------------------


class TestSyncResult:
    def test_success_result_fields(self) -> None:
        from sophia.gui.services.chronos_service import SyncResult

        result = SyncResult(status="success", deadline_count=5, course_count=3, deadlines=[])
        assert result.status == "success"
        assert result.deadline_count == 5
        assert result.course_count == 3
        assert result.error_message is None

    def test_auth_expired_result(self) -> None:
        from sophia.gui.services.chronos_service import SyncResult

        result = SyncResult(
            status="auth_expired",
            error_message="Session expired",
        )
        assert result.status == "auth_expired"
        assert result.deadline_count == 0
        assert result.error_message == "Session expired"

    def test_network_error_result(self) -> None:
        from sophia.gui.services.chronos_service import SyncResult

        result = SyncResult(
            status="network_error",
            error_message="Connection refused",
        )
        assert result.status == "network_error"
        assert result.deadline_count == 0

    def test_default_deadlines_is_empty_list(self) -> None:
        from sophia.gui.services.chronos_service import SyncResult

        result = SyncResult(status="success")
        assert result.deadlines == []


# -- sync_deadlines_from_gui (enhanced) -------------------------------------


class TestSyncDeadlinesFromGuiEnhanced:
    """Test enhanced sync wrapper with SyncResult and progress callback."""

    @pytest.mark.asyncio
    async def test_success_returns_sync_result(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import SyncResult, sync_deadlines_from_gui

        deadlines = [_make_deadline(), _make_deadline(id="dl-2")]
        with patch(
            f"{_PATCH_BASE}._sync_deadlines",
            new_callable=AsyncMock,
            return_value=deadlines,
        ):
            result = await sync_deadlines_from_gui(mock_container)

        assert isinstance(result, SyncResult)
        assert result.status == "success"
        assert result.deadline_count == 2
        assert result.deadlines == deadlines

    @pytest.mark.asyncio
    async def test_auth_error_returns_auth_expired(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import SyncResult, sync_deadlines_from_gui

        with patch(
            f"{_PATCH_BASE}._sync_deadlines",
            new_callable=AsyncMock,
            side_effect=AuthError("token expired"),
        ):
            result = await sync_deadlines_from_gui(mock_container)

        assert isinstance(result, SyncResult)
        assert result.status == "auth_expired"
        assert result.deadline_count == 0

    @pytest.mark.asyncio
    async def test_network_error_returns_network_status(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import SyncResult, sync_deadlines_from_gui

        with patch(
            f"{_PATCH_BASE}._sync_deadlines",
            new_callable=AsyncMock,
            side_effect=ConnectionError("connection refused"),
        ):
            result = await sync_deadlines_from_gui(mock_container)

        assert isinstance(result, SyncResult)
        assert result.status == "network_error"

    @pytest.mark.asyncio
    async def test_generic_error_returns_error_status(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import SyncResult, sync_deadlines_from_gui

        with patch(
            f"{_PATCH_BASE}._sync_deadlines",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected"),
        ):
            result = await sync_deadlines_from_gui(mock_container)

        assert isinstance(result, SyncResult)
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_progress_callback_invoked(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import sync_deadlines_from_gui

        callback = AsyncMock()
        deadlines = [_make_deadline()]
        with patch(
            f"{_PATCH_BASE}._sync_deadlines",
            new_callable=AsyncMock,
            return_value=deadlines,
        ):
            await sync_deadlines_from_gui(mock_container, progress_callback=callback)

        callback.assert_called()


# -- record_manual_time_entry ------------------------------------------------


# -- compute_effort_distribution (pure function) ----------------------------


class TestComputeEffortDistribution:
    """Parametrised tests for the pure distribution algorithm."""

    def test_empty_deadlines_returns_empty(self) -> None:
        from sophia.gui.services.chronos_service import compute_effort_distribution

        result = compute_effort_distribution(
            deadlines=[],
            estimates={},
            tracked={},
            today="2026-03-28",
            horizon_days=14,
        )
        assert result == []

    def test_single_deadline_spreads_remaining_evenly(self) -> None:
        """10h estimated, 4h tracked → 6h spread over 3 days."""
        from sophia.gui.services.chronos_service import compute_effort_distribution

        dl = _make_deadline(
            id="dl-1",
            name="HW 1",
            due_at=datetime(2026, 3, 31, 23, 59, tzinfo=UTC),
        )
        result = compute_effort_distribution(
            deadlines=[dl],
            estimates={"dl-1": 10.0},
            tracked={"dl-1": 4.0},
            today="2026-03-28",
            horizon_days=14,
        )
        # Days: Mar 28, 29, 30, 31 → 4 days (today through due date)
        dl1_hours = [d.deadline_efforts.get("HW 1", 0.0) for d in result]
        total_assigned = sum(dl1_hours)
        assert abs(total_assigned - 6.0) < 0.01
        # Each of the 4 days gets ~1.5h
        assigned_days = [d for d in result if d.deadline_efforts.get("HW 1", 0.0) > 0]
        assert len(assigned_days) == 4

    def test_multiple_deadlines_stack_correctly(self) -> None:
        from sophia.gui.services.chronos_service import compute_effort_distribution

        dl1 = _make_deadline(
            id="dl-1",
            name="HW 1",
            due_at=datetime(2026, 3, 30, 23, 59, tzinfo=UTC),
        )
        dl2 = _make_deadline(
            id="dl-2",
            name="Quiz 2",
            due_at=datetime(2026, 3, 30, 23, 59, tzinfo=UTC),
        )
        result = compute_effort_distribution(
            deadlines=[dl1, dl2],
            estimates={"dl-1": 6.0, "dl-2": 3.0},
            tracked={"dl-1": 0.0, "dl-2": 0.0},
            today="2026-03-28",
            horizon_days=14,
        )
        # Both deadlines share Mar 28, 29, 30 → 3 days
        day_28 = next(d for d in result if d.date == "2026-03-28")
        hw1 = day_28.deadline_efforts.get("HW 1", 0.0)
        quiz2 = day_28.deadline_efforts.get("Quiz 2", 0.0)
        assert hw1 > 0
        assert quiz2 > 0
        assert abs(day_28.total - hw1 - quiz2) < 0.01

    def test_deadline_due_today_all_effort_on_today(self) -> None:
        from sophia.gui.services.chronos_service import compute_effort_distribution

        dl = _make_deadline(
            id="dl-1",
            name="HW 1",
            due_at=datetime(2026, 3, 28, 23, 59, tzinfo=UTC),
        )
        result = compute_effort_distribution(
            deadlines=[dl],
            estimates={"dl-1": 5.0},
            tracked={"dl-1": 2.0},
            today="2026-03-28",
            horizon_days=14,
        )
        day_28 = next(d for d in result if d.date == "2026-03-28")
        assert abs(day_28.deadline_efforts["HW 1"] - 3.0) < 0.01

    def test_past_deadline_excluded(self) -> None:
        from sophia.gui.services.chronos_service import compute_effort_distribution

        dl = _make_deadline(
            id="dl-1",
            name="HW 1",
            due_at=datetime(2026, 3, 27, 23, 59, tzinfo=UTC),
        )
        result = compute_effort_distribution(
            deadlines=[dl],
            estimates={"dl-1": 5.0},
            tracked={"dl-1": 0.0},
            today="2026-03-28",
            horizon_days=14,
        )
        dl1_hours = sum(d.deadline_efforts.get("HW 1", 0.0) for d in result)
        assert dl1_hours == 0.0

    def test_unestimated_deadline_shows_in_unestimated_list(self) -> None:
        from sophia.gui.services.chronos_service import compute_effort_distribution

        dl = _make_deadline(
            id="dl-1",
            name="HW 1",
            due_at=datetime(2026, 3, 31, 23, 59, tzinfo=UTC),
        )
        result = compute_effort_distribution(
            deadlines=[dl],
            estimates={},  # no estimate
            tracked={"dl-1": 0.0},
            today="2026-03-28",
            horizon_days=14,
        )
        day_28 = next(d for d in result if d.date == "2026-03-28")
        assert "HW 1" in day_28.unestimated
        assert day_28.deadline_efforts.get("HW 1", 0.0) == 0.0

    def test_tracked_exceeds_estimate_zero_remaining(self) -> None:
        from sophia.gui.services.chronos_service import compute_effort_distribution

        dl = _make_deadline(
            id="dl-1",
            name="HW 1",
            due_at=datetime(2026, 3, 31, 23, 59, tzinfo=UTC),
        )
        result = compute_effort_distribution(
            deadlines=[dl],
            estimates={"dl-1": 5.0},
            tracked={"dl-1": 7.0},  # exceeds estimate
            today="2026-03-28",
            horizon_days=14,
        )
        total = sum(d.deadline_efforts.get("HW 1", 0.0) for d in result)
        assert total == 0.0

    def test_result_length_matches_horizon(self) -> None:
        from sophia.gui.services.chronos_service import compute_effort_distribution

        result = compute_effort_distribution(
            deadlines=[],
            estimates={},
            tracked={},
            today="2026-03-28",
            horizon_days=14,
        )
        # Empty deadlines → empty (no days with data)
        assert len(result) == 0

    def test_days_are_ordered_chronologically(self) -> None:
        from sophia.gui.services.chronos_service import compute_effort_distribution

        dl = _make_deadline(
            id="dl-1",
            name="HW 1",
            due_at=datetime(2026, 4, 5, 23, 59, tzinfo=UTC),
        )
        result = compute_effort_distribution(
            deadlines=[dl],
            estimates={"dl-1": 14.0},
            tracked={"dl-1": 0.0},
            today="2026-03-28",
            horizon_days=14,
        )
        dates = [d.date for d in result]
        assert dates == sorted(dates)

    def test_deadline_beyond_horizon_clipped(self) -> None:
        """A deadline due in 20 days only distributes across the 14-day horizon."""
        from sophia.gui.services.chronos_service import compute_effort_distribution

        dl = _make_deadline(
            id="dl-1",
            name="HW 1",
            due_at=datetime(2026, 4, 17, 23, 59, tzinfo=UTC),  # 20 days away
        )
        result = compute_effort_distribution(
            deadlines=[dl],
            estimates={"dl-1": 14.0},
            tracked={"dl-1": 0.0},
            today="2026-03-28",
            horizon_days=14,
        )
        assert len(result) == 14
        total = sum(d.deadline_efforts.get("HW 1", 0.0) for d in result)
        # All 14h spread across 14 days (even though due in 20)
        assert abs(total - 14.0) < 0.01


# -- build_effort_chart_config (pure function) ------------------------------


class TestBuildEffortChartConfig:
    def test_returns_valid_echart_structure(self) -> None:
        from sophia.gui.services.chronos_service import (
            DayEffort,
            build_effort_chart_config,
        )

        days = [
            DayEffort(
                date="2026-03-28",
                deadline_efforts={"HW 1": 2.0, "Quiz": 1.0},
                unestimated=[],
                total=3.0,
            ),
            DayEffort(
                date="2026-03-29",
                deadline_efforts={"HW 1": 2.0},
                unestimated=["Lab Report"],
                total=2.0,
            ),
        ]
        config = build_effort_chart_config(days, capacity=4.0)
        assert "xAxis" in config
        assert "yAxis" in config
        assert "series" in config
        assert config["xAxis"]["type"] == "category"
        # Dates on x-axis
        assert config["xAxis"]["data"] == ["2026-03-28", "2026-03-29"]

    def test_includes_capacity_markline(self) -> None:
        from sophia.gui.services.chronos_service import (
            DayEffort,
            build_effort_chart_config,
        )

        days = [
            DayEffort(date="2026-03-28", deadline_efforts={"HW 1": 5.0}, unestimated=[], total=5.0),
        ]
        config = build_effort_chart_config(days, capacity=4.0)
        # At least one series should have a markLine with capacity
        has_markline = any("markLine" in s for s in config["series"])
        assert has_markline

    def test_stacked_bar_type(self) -> None:
        from sophia.gui.services.chronos_service import (
            DayEffort,
            build_effort_chart_config,
        )

        days = [
            DayEffort(
                date="2026-03-28",
                deadline_efforts={"HW 1": 2.0, "Quiz": 1.5},
                unestimated=[],
                total=3.5,
            ),
        ]
        config = build_effort_chart_config(days, capacity=4.0)
        bar_series = [s for s in config["series"] if s["type"] == "bar"]
        assert len(bar_series) >= 2
        for s in bar_series:
            assert s.get("stack") == "effort"

    def test_unestimated_series_included(self) -> None:
        from sophia.gui.services.chronos_service import (
            DayEffort,
            build_effort_chart_config,
        )

        days = [
            DayEffort(
                date="2026-03-28",
                deadline_efforts={},
                unestimated=["Lab Report"],
                total=0.0,
            ),
        ]
        config = build_effort_chart_config(days, capacity=4.0)
        names = [s["name"] for s in config["series"]]
        assert "Unestimated" in names

    def test_empty_days_returns_minimal_config(self) -> None:
        from sophia.gui.services.chronos_service import build_effort_chart_config

        config = build_effort_chart_config([], capacity=4.0)
        assert config["xAxis"]["data"] == []
        assert config["series"] == []


# -- get_effort_distribution_data (async wrapper) ---------------------------


class TestGetEffortDistributionData:
    @pytest.mark.asyncio
    async def test_happy_path(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_effort_distribution_data

        dl = _make_deadline(
            id="dl-1",
            name="HW 1",
            due_at=datetime.now(UTC) + timedelta(days=7),
        )

        with (
            patch(
                f"{_PATCH_BASE}._get_deadlines",
                new_callable=AsyncMock,
                return_value=[dl],
            ),
            patch(
                f"{_PATCH_BASE}._get_tracked_time",
                new_callable=AsyncMock,
                return_value=2.0,
            ),
        ):
            # Mock the estimate fetch
            cursor = AsyncMock()
            cursor.fetchone = AsyncMock(return_value=(5.0,))
            mock_container.db.execute = AsyncMock(return_value=cursor)

            result = await get_effort_distribution_data(mock_container)

        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_effort_distribution_data

        with patch(
            f"{_PATCH_BASE}._get_deadlines",
            new_callable=AsyncMock,
            side_effect=Exception("db error"),
        ):
            result = await get_effort_distribution_data(mock_container)

        assert result == []


class TestRecordManualTimeEntry:
    @pytest.mark.asyncio
    async def test_delegates_to_core(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import record_manual_time_entry

        with patch(
            f"{_PATCH_BASE}._record_time",
            new_callable=AsyncMock,
        ) as mock_fn:
            await record_manual_time_entry(mock_container, "dl-1", 2.5, note="Offline study")

        mock_fn.assert_awaited_once_with(
            mock_container.db,
            "dl-1",
            2.5,
            "Offline study",
            recorded_at=None,
        )

    @pytest.mark.asyncio
    async def test_swallows_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import record_manual_time_entry

        with patch(
            f"{_PATCH_BASE}._record_time",
            new_callable=AsyncMock,
            side_effect=Exception("db locked"),
        ):
            await record_manual_time_entry(mock_container, "dl-1", 1.0)


# -- get_time_entries --------------------------------------------------------


class TestGetTimeEntries:
    @pytest.mark.asyncio
    async def test_returns_entries(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_time_entries

        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(
            return_value=[
                (1.0, "timer", None, "2026-03-28T10:00:00"),
                (0.5, "manual", "Reading", "2026-03-28T12:00:00"),
            ]
        )
        mock_container.db.execute = AsyncMock(return_value=cursor)

        result = await get_time_entries(mock_container, "dl-1")

        assert len(result) == 2
        assert result[0]["source"] == "timer"
        assert result[1]["hours"] == 0.5

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_time_entries

        mock_container.db.execute = AsyncMock(side_effect=Exception("db error"))

        result = await get_time_entries(mock_container, "dl-1")

        assert result == []


# -- get_past_deadlines ------------------------------------------------------


class TestGetPastDeadlines:
    @pytest.mark.asyncio
    async def test_returns_deadlines(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_past_deadlines

        expected = [_make_deadline()]
        with patch(
            f"{_PATCH_BASE}._get_missed_deadlines",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fn:
            result = await get_past_deadlines(mock_container)

        assert result == expected
        mock_fn.assert_awaited_once_with(mock_container.db, course_id=None, limit=50)

    @pytest.mark.asyncio
    async def test_passes_course_filter(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_past_deadlines

        with patch(
            f"{_PATCH_BASE}._get_missed_deadlines",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fn:
            await get_past_deadlines(mock_container, course_id=COURSE_ID)

        mock_fn.assert_awaited_once_with(mock_container.db, course_id=COURSE_ID, limit=50)

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_past_deadlines

        with patch(
            f"{_PATCH_BASE}._get_missed_deadlines",
            new_callable=AsyncMock,
            side_effect=Exception("db down"),
        ):
            result = await get_past_deadlines(mock_container)

        assert result == []


# -- get_deadline_reflection -------------------------------------------------


class TestGetDeadlineReflection:
    @pytest.mark.asyncio
    async def test_returns_reflection_data(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_reflection

        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(3.0, 5.0, "Took longer than expected"))
        mock_container.db.execute = AsyncMock(return_value=cursor)

        result = await get_deadline_reflection(mock_container, DEADLINE_ID)

        assert result is not None
        assert result["predicted_hours"] == 3.0
        assert result["actual_hours"] == 5.0
        assert result["reflection_text"] == "Took longer than expected"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_reflection(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_reflection

        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)
        mock_container.db.execute = AsyncMock(return_value=cursor)

        result = await get_deadline_reflection(mock_container, DEADLINE_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import get_deadline_reflection

        mock_container.db.execute = AsyncMock(side_effect=Exception("db error"))

        result = await get_deadline_reflection(mock_container, DEADLINE_ID)

        assert result is None


# -- export_deadlines_ics ----------------------------------------------------


class TestExportDeadlinesIcs:
    @pytest.mark.asyncio
    async def test_returns_ics_string(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import export_deadlines_ics

        ics_content = "BEGIN:VCALENDAR\nEND:VCALENDAR"
        with patch(
            f"{_PATCH_BASE}._export_deadlines_ics",
            new_callable=AsyncMock,
            return_value=ics_content,
        ) as mock_fn:
            result = await export_deadlines_ics(mock_container)

        assert result == ics_content
        mock_fn.assert_awaited_once_with(mock_container.db, horizon_days=30)

    @pytest.mark.asyncio
    async def test_passes_horizon_days(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import export_deadlines_ics

        with patch(
            f"{_PATCH_BASE}._export_deadlines_ics",
            new_callable=AsyncMock,
            return_value="",
        ) as mock_fn:
            await export_deadlines_ics(mock_container, horizon_days=7)

        mock_fn.assert_awaited_once_with(mock_container.db, horizon_days=7)

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.chronos_service import export_deadlines_ics

        with patch(
            f"{_PATCH_BASE}._export_deadlines_ics",
            new_callable=AsyncMock,
            side_effect=Exception("ical crash"),
        ):
            result = await export_deadlines_ics(mock_container)

        assert result is None
