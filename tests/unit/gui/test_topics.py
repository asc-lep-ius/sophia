"""Tests for the Topics management page — pure helpers and constants."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# format_confidence_level
# ---------------------------------------------------------------------------


class TestFormatConfidenceLevel:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.0, "No idea"),
            (0.15, "No idea"),
            (0.2, "Guessing"),
            (0.35, "Guessing"),
            (0.4, "Partial"),
            (0.55, "Partial"),
            (0.6, "Mostly right"),
            (0.75, "Mostly right"),
            (0.8, "Certain"),
            (1.0, "Certain"),
        ],
    )
    def test_maps_score_to_label(self, score: float, expected: str) -> None:
        from sophia.gui.pages.topics import format_confidence_level

        assert format_confidence_level(score) == expected

    def test_none_returns_not_rated(self) -> None:
        from sophia.gui.pages.topics import format_confidence_level

        assert format_confidence_level(None) == "Not rated"


# ---------------------------------------------------------------------------
# classify_calibration
# ---------------------------------------------------------------------------


class TestClassifyCalibration:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (None, "pending"),
            (0.0, "well_calibrated"),
            (0.1, "well_calibrated"),
            (-0.1, "well_calibrated"),
            (0.15, "slightly_over"),
            (-0.15, "slightly_under"),
            (0.25, "blind_spot"),
            (0.5, "blind_spot"),
            (-0.25, "underconfident"),
            (-0.5, "underconfident"),
        ],
    )
    def test_classifies_calibration_error(self, error: float | None, expected: str) -> None:
        from sophia.gui.pages.topics import classify_calibration

        assert classify_calibration(error) == expected


# ---------------------------------------------------------------------------
# SOURCE_BADGE_COLORS constant
# ---------------------------------------------------------------------------


class TestSourceBadgeColors:
    def test_has_all_sources(self) -> None:
        from sophia.gui.pages.topics import SOURCE_BADGE_COLORS

        assert "lecture" in SOURCE_BADGE_COLORS
        assert "quiz" in SOURCE_BADGE_COLORS
        assert "manual" in SOURCE_BADGE_COLORS

    def test_lecture_is_blue(self) -> None:
        from sophia.gui.pages.topics import SOURCE_BADGE_COLORS

        assert SOURCE_BADGE_COLORS["lecture"] == "blue"


# ---------------------------------------------------------------------------
# CALIBRATION_LABELS constant
# ---------------------------------------------------------------------------


class TestCalibrationLabels:
    def test_has_all_classifications(self) -> None:
        from sophia.gui.pages.topics import CALIBRATION_LABELS

        expected_keys = {
            "pending",
            "well_calibrated",
            "slightly_over",
            "slightly_under",
            "blind_spot",
            "underconfident",
        }
        assert set(CALIBRATION_LABELS.keys()) == expected_keys


# ---------------------------------------------------------------------------
# ANKI_NUDGE_TEXT constant
# ---------------------------------------------------------------------------


class TestAnkiNudgeText:
    def test_nudge_text_exists_and_is_nonempty(self) -> None:
        from sophia.gui.pages.topics import ANKI_NUDGE_TEXT

        assert isinstance(ANKI_NUDGE_TEXT, str)
        assert len(ANKI_NUDGE_TEXT) > 10
