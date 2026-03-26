"""Tests for GUI calibration service wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from sophia.domain.models import ConfidenceRating, StudySession

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

COURSE_ID = 42
TOPIC = "Binary Search"

_PATCH_BASE = "sophia.gui.services.calibration_service"


def _make_rating(**overrides: Any) -> ConfidenceRating:
    defaults = {
        "topic": TOPIC,
        "course_id": COURSE_ID,
        "predicted": 0.8,
        "actual": 0.6,
        "rated_at": "2026-01-01T00:00:00",
    }
    defaults.update(overrides)
    return ConfidenceRating(**defaults)  # type: ignore[arg-type]


def _make_session(**overrides: Any) -> StudySession:
    defaults = {
        "id": 1,
        "course_id": COURSE_ID,
        "topic": TOPIC,
        "pre_test_score": 0.4,
        "post_test_score": 0.7,
        "started_at": "2026-01-01T10:00:00",
        "completed_at": "2026-01-01T11:00:00",
    }
    defaults.update(overrides)
    return StudySession(**defaults)  # type: ignore[arg-type]


# -- get_calibration_ratings -------------------------------------------------


class TestGetCalibrationRatings:
    @pytest.mark.asyncio
    async def test_returns_ratings(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.calibration_service import get_calibration_ratings

        expected = [_make_rating()]
        with patch(
            f"{_PATCH_BASE}._get_confidence_ratings",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fn:
            result = await get_calibration_ratings(mock_container, COURSE_ID)

        assert result == expected
        mock_fn.assert_awaited_once_with(mock_container.db, COURSE_ID)

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.calibration_service import get_calibration_ratings

        with patch(
            f"{_PATCH_BASE}._get_confidence_ratings",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await get_calibration_ratings(mock_container, COURSE_ID)

        assert result == []


# -- get_blind_spot_topics ---------------------------------------------------


class TestGetBlindSpotTopics:
    @pytest.mark.asyncio
    async def test_returns_blind_spots(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.calibration_service import get_blind_spot_topics

        expected = [_make_rating(predicted=0.9, actual=0.3)]
        with patch(
            f"{_PATCH_BASE}._get_blind_spots",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            result = await get_blind_spot_topics(mock_container, COURSE_ID)

        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.calibration_service import get_blind_spot_topics

        with patch(
            f"{_PATCH_BASE}._get_blind_spots",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await get_blind_spot_topics(mock_container, COURSE_ID)

        assert result == []


# -- get_course_avg_confidence -----------------------------------------------


class TestGetCourseAvgConfidence:
    @pytest.mark.asyncio
    async def test_returns_value(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.calibration_service import get_course_avg_confidence

        with patch(
            f"{_PATCH_BASE}._get_course_confidence",
            new_callable=AsyncMock,
            return_value=0.72,
        ):
            result = await get_course_avg_confidence(mock_container, COURSE_ID)

        assert result == 0.72

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.calibration_service import get_course_avg_confidence

        with patch(
            f"{_PATCH_BASE}._get_course_confidence",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await get_course_avg_confidence(mock_container, COURSE_ID)

        assert result is None


# -- get_study_sessions_for_topic --------------------------------------------


class TestGetStudySessionsForTopic:
    @pytest.mark.asyncio
    async def test_returns_sessions(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.calibration_service import get_study_sessions_for_topic

        expected = [_make_session()]
        with patch(
            f"{_PATCH_BASE}._get_study_sessions",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fn:
            result = await get_study_sessions_for_topic(mock_container, COURSE_ID, TOPIC)

        assert result == expected
        mock_fn.assert_awaited_once_with(mock_container.db, COURSE_ID, TOPIC)

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.calibration_service import get_study_sessions_for_topic

        with patch(
            f"{_PATCH_BASE}._get_study_sessions",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = await get_study_sessions_for_topic(mock_container, COURSE_ID, TOPIC)

        assert result == []


# -- compute_tier_progression (pure) -----------------------------------------


class TestComputeTierProgression:
    def test_maps_sessions_to_tiers(self) -> None:
        from sophia.gui.services.calibration_service import compute_tier_progression

        sessions = [
            _make_session(id=1, post_test_score=0.3),
            _make_session(id=2, post_test_score=0.6),
            _make_session(id=3, post_test_score=0.85),
        ]
        result = compute_tier_progression(sessions)

        assert len(result) == 3
        assert result[0]["session"] == 0
        assert result[0]["tier"] == "cued"
        assert result[2]["tier"] == "transfer"

    def test_empty_sessions(self) -> None:
        from sophia.gui.services.calibration_service import compute_tier_progression

        assert compute_tier_progression([]) == []

    def test_none_score_uses_cued(self) -> None:
        from sophia.gui.services.calibration_service import compute_tier_progression

        sessions = [_make_session(post_test_score=None)]
        result = compute_tier_progression(sessions)

        assert result[0]["tier"] == "cued"
        assert result[0]["score"] == 0.0


# -- build_confidence_scatter_data (pure) ------------------------------------


class TestBuildConfidenceScatterData:
    def test_returns_echarts_config(self) -> None:
        from sophia.gui.services.calibration_service import (
            build_confidence_scatter_data,
        )

        ratings = [
            _make_rating(topic="A", predicted=0.8, actual=0.6),
            _make_rating(topic="B", predicted=0.5, actual=0.7),
        ]
        result = build_confidence_scatter_data(ratings)

        assert "series" in result
        assert len(result["series"][0]["data"]) == 2

    def test_skips_ratings_without_actual(self) -> None:
        from sophia.gui.services.calibration_service import (
            build_confidence_scatter_data,
        )

        ratings = [
            _make_rating(actual=None),
            _make_rating(topic="B", actual=0.7),
        ]
        result = build_confidence_scatter_data(ratings)

        assert len(result["series"][0]["data"]) == 1

    def test_empty_ratings(self) -> None:
        from sophia.gui.services.calibration_service import (
            build_confidence_scatter_data,
        )

        result = build_confidence_scatter_data([])
        assert result["series"][0]["data"] == []


# -- build_blind_spot_chart_data (pure) --------------------------------------


class TestBuildBlindSpotChartData:
    def test_returns_horizontal_bar_config(self) -> None:
        from sophia.gui.services.calibration_service import build_blind_spot_chart_data

        ratings = [
            _make_rating(topic="A", predicted=0.9, actual=0.4),
            _make_rating(topic="B", predicted=0.7, actual=0.3),
        ]
        result = build_blind_spot_chart_data(ratings)

        assert "yAxis" in result
        assert "series" in result
        assert len(result["series"][0]["data"]) == 2

    def test_empty_ratings(self) -> None:
        from sophia.gui.services.calibration_service import build_blind_spot_chart_data

        result = build_blind_spot_chart_data([])
        assert result["series"][0]["data"] == []


# -- build_mastery_heatmap_data (pure) ---------------------------------------


class TestBuildMasteryHeatmapData:
    def test_returns_heatmap_config(self) -> None:
        from sophia.gui.services.calibration_service import build_mastery_heatmap_data

        ratings = [
            _make_rating(topic="A", course_id=1, predicted=0.8, actual=0.7),
            _make_rating(topic="B", course_id=1, predicted=0.5, actual=0.3),
            _make_rating(topic="A", course_id=2, predicted=0.6, actual=0.9),
        ]
        result = build_mastery_heatmap_data(ratings)

        assert "series" in result
        assert "visualMap" in result
        assert len(result["series"][0]["data"]) == 3

    def test_empty_ratings(self) -> None:
        from sophia.gui.services.calibration_service import build_mastery_heatmap_data

        result = build_mastery_heatmap_data([])
        assert result["series"][0]["data"] == []
