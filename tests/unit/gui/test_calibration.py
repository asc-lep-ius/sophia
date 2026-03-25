"""Tests for the calibration dashboard page — pure helpers and constants."""

from __future__ import annotations

import pytest

from sophia.domain.models import ConfidenceRating

# --- Pure helper tests -------------------------------------------------------


class TestGetCurrentTier:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (None, "cued"),
            (0.0, "cued"),
            (0.39, "cued"),
            (0.4, "explain"),
            (0.69, "explain"),
            (0.7, "transfer"),
            (1.0, "transfer"),
        ],
    )
    def test_maps_score_to_tier(self, score: float | None, expected: str) -> None:
        from sophia.gui.pages.calibration import get_current_tier

        assert get_current_tier(score) == expected


class TestFormatSocraticFeedback:
    def test_contains_topic_and_tier(self) -> None:
        from sophia.gui.pages.calibration import format_socratic_feedback

        result = format_socratic_feedback("Analysis", "explain", 5, 0.72)
        assert "Analysis" in result
        assert "EXPLAIN" in result
        assert "5 session(s)" in result
        assert "72%" in result

    def test_never_says_you_should(self) -> None:
        from sophia.gui.pages.calibration import format_socratic_feedback

        result = format_socratic_feedback("Topology", "cued", 3, 0.3)
        assert "you should" not in result.lower()
        assert "you must" not in result.lower()

    def test_ends_with_question(self) -> None:
        from sophia.gui.pages.calibration import format_socratic_feedback

        result = format_socratic_feedback("Algebra", "transfer", 10, 0.9)
        assert result.rstrip().endswith("?")


class TestBuildCalibrationTrendData:
    def test_returns_echarts_config(self) -> None:
        from sophia.gui.pages.calibration import build_calibration_trend_data

        ratings = [
            ConfidenceRating(
                topic="A", course_id=1, predicted=0.8, actual=0.6, rated_at="2026-01-01"
            ),
            ConfidenceRating(
                topic="B", course_id=1, predicted=0.5, actual=0.7, rated_at="2026-01-02"
            ),
        ]
        result = build_calibration_trend_data(ratings)
        assert "series" in result
        assert len(result["series"][0]["data"]) == 2
        assert result["series"][0]["data"][0] == pytest.approx(0.2)
        assert result["series"][0]["data"][1] == pytest.approx(0.2)

    def test_empty_ratings(self) -> None:
        from sophia.gui.pages.calibration import build_calibration_trend_data

        result = build_calibration_trend_data([])
        assert result["series"][0]["data"] == []

    def test_skips_ratings_without_actual(self) -> None:
        from sophia.gui.pages.calibration import build_calibration_trend_data

        ratings = [
            ConfidenceRating(topic="A", course_id=1, predicted=0.8, actual=None),
            ConfidenceRating(
                topic="B", course_id=1, predicted=0.5, actual=0.7, rated_at="2026-01-01"
            ),
        ]
        result = build_calibration_trend_data(ratings)
        assert len(result["series"][0]["data"]) == 1


class TestBuildTierProgressionChart:
    def test_returns_chart_with_data(self) -> None:
        from sophia.gui.pages.calibration import build_tier_progression_chart

        progression = [
            {"session": 1, "tier": "cued", "score": 0.3},
            {"session": 2, "tier": "explain", "score": 0.6},
            {"session": 3, "tier": "transfer", "score": 0.85},
        ]
        result = build_tier_progression_chart(progression, "Algebra")
        assert "Algebra" in result["title"]["text"]
        assert result["series"][0]["data"] == [0, 1, 2]

    def test_empty_progression(self) -> None:
        from sophia.gui.pages.calibration import build_tier_progression_chart

        result = build_tier_progression_chart([], "Test")
        assert result["series"][0]["data"] == []


class TestConstants:
    def test_overconfident_threshold(self) -> None:
        from sophia.gui.pages.calibration import _OVERCONFIDENT_THRESHOLD

        assert _OVERCONFIDENT_THRESHOLD == 0.2

    def test_dangerous_threshold(self) -> None:
        from sophia.gui.pages.calibration import _DANGEROUS_THRESHOLD

        assert _DANGEROUS_THRESHOLD == 0.3

    def test_tier_thresholds_keys(self) -> None:
        from sophia.gui.pages.calibration import _TIER_THRESHOLDS

        assert set(_TIER_THRESHOLDS.keys()) == {"cued", "explain", "transfer"}

    def test_tier_y_map_values(self) -> None:
        from sophia.gui.pages.calibration import _TIER_Y_MAP

        assert _TIER_Y_MAP == {"cued": 0, "explain": 1, "transfer": 2}


class TestExports:
    def test_calibration_content_callable(self) -> None:
        from sophia.gui.pages.calibration import calibration_content

        assert callable(calibration_content)

    def test_get_current_tier_callable(self) -> None:
        from sophia.gui.pages.calibration import get_current_tier

        assert callable(get_current_tier)
