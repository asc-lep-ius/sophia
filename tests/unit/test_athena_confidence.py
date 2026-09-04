"""Tests for the Athena confidence service — confidence-before-reveal metacognitive workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from sophia.domain.models import ConfidenceRating

from .._sql import exec_sql

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def app_container(db: AsyncSession) -> MagicMock:
    """Minimal AppContainer mock wired to the in-memory DB."""
    container = MagicMock()
    container.db = db
    return container


# ---------------------------------------------------------------------------
# ConfidenceRating model
# ---------------------------------------------------------------------------


class TestConfidenceRatingModel:
    def test_calibration_error_no_actual(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.75)
        assert r.calibration_error is None

    def test_calibration_error_overconfident(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.75, actual=0.5)
        assert r.calibration_error == pytest.approx(0.25)  # pyright: ignore[reportUnknownMemberType]

    def test_calibration_error_underconfident(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.25, actual=0.75)
        assert r.calibration_error == pytest.approx(-0.5)  # pyright: ignore[reportUnknownMemberType]

    def test_calibration_error_perfect(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.5, actual=0.5)
        assert r.calibration_error == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]

    def test_is_blind_spot_true(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.8, actual=0.3)
        assert r.is_blind_spot is True

    def test_is_blind_spot_false_small_error(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.6, actual=0.5)
        assert r.is_blind_spot is False

    def test_is_blind_spot_false_no_actual(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.8)
        assert r.is_blind_spot is False

    def test_is_blind_spot_false_underconfident(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.3, actual=0.8)
        assert r.is_blind_spot is False

    def test_is_blind_spot_boundary_not_blind_spot(self) -> None:
        """Exactly 0.2 delta is NOT a blind spot (threshold is >0.2)."""
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.7, actual=0.5)
        assert r.is_blind_spot is False


# ---------------------------------------------------------------------------
# rating_to_score
# ---------------------------------------------------------------------------


class TestRatingToScore:
    @pytest.mark.parametrize(
        ("rating", "expected"),
        [
            (1, 0.0),
            (2, 0.25),
            (3, 0.5),
            (4, 0.75),
            (5, 1.0),
        ],
    )
    def test_valid_ratings(self, rating: int, expected: float) -> None:
        from sophia.services.athena_confidence import rating_to_score

        assert rating_to_score(rating) == pytest.approx(expected)  # pyright: ignore[reportUnknownMemberType]

    def test_clamps_below_minimum(self) -> None:
        from sophia.services.athena_confidence import rating_to_score

        assert rating_to_score(0) == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]
        assert rating_to_score(-5) == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]

    def test_clamps_above_maximum(self) -> None:
        from sophia.services.athena_confidence import rating_to_score

        assert rating_to_score(6) == pytest.approx(1.0)  # pyright: ignore[reportUnknownMemberType]
        assert rating_to_score(100) == pytest.approx(1.0)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# rate_confidence
# ---------------------------------------------------------------------------


class TestRateConfidence:
    @pytest.mark.asyncio
    async def test_stores_and_returns_rating(self, db: AsyncSession) -> None:
        from sophia.services.athena_confidence import rate_confidence

        result = await rate_confidence(db, "Sorting", course_id=42, rating=4)

        assert isinstance(result, ConfidenceRating)
        assert result.topic == "Sorting"
        assert result.course_id == 42
        assert result.predicted == pytest.approx(0.75)  # pyright: ignore[reportUnknownMemberType]
        assert result.actual is None
        assert result.rated_at != ""

    @pytest.mark.asyncio
    async def test_persists_to_database(self, app_container: MagicMock, db: AsyncSession) -> None:
        from sophia.services.athena_confidence import rate_confidence

        await rate_confidence(db, "Hashing", course_id=42, rating=2)

        cursor = await exec_sql(db, "SELECT topic, predicted FROM confidence_ratings")
        rows = list(cursor.fetchall())
        assert len(rows) == 1
        assert rows[0][0] == "Hashing"
        assert rows[0][1] == pytest.approx(0.25)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# get_confidence_ratings
# ---------------------------------------------------------------------------


class TestGetConfidenceRatings:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_data(self, db: AsyncSession) -> None:
        from sophia.services.athena_confidence import get_confidence_ratings

        result = await get_confidence_ratings(db, course_id=99)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_latest_per_topic(self, db: AsyncSession) -> None:
        from sophia.services.athena_confidence import get_confidence_ratings

        # Insert two ratings for same topic — second should win
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.25),
        )
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.75),
        )
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Hashing", 42, 0.5),
        )

        result = await get_confidence_ratings(db, course_id=42)
        assert len(result) == 2

        by_topic = {r.topic: r for r in result}
        assert by_topic["Sorting"].predicted == pytest.approx(0.75)  # pyright: ignore[reportUnknownMemberType]
        assert by_topic["Hashing"].predicted == pytest.approx(0.5)  # pyright: ignore[reportUnknownMemberType]

    @pytest.mark.asyncio
    async def test_filters_by_course_id(self, db: AsyncSession) -> None:
        from sophia.services.athena_confidence import get_confidence_ratings

        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.5),
        )
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 99, 0.75),
        )

        result = await get_confidence_ratings(db, course_id=42)
        assert len(result) == 1
        assert result[0].course_id == 42

    @pytest.mark.asyncio
    async def test_unscoped_call_never_surfaces_a_learners_owned_rating(
        self, db: AsyncSession
    ) -> None:
        """The write side (update_actual_score) is restricted to owner-less
        rows when called without a learner; the read side must match, or a
        legacy PATCH that correctly updated the owner-less row would appear
        to have done nothing while actually exposing another learner's row."""
        from sophia.services.athena_confidence import get_confidence_ratings

        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.25),
        )
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted, user_id) "
            "VALUES (?, ?, ?, ?)",
            ("Sorting", 42, 0.9, "learner"),
        )

        result = await get_confidence_ratings(db, course_id=42)

        assert len(result) == 1
        assert result[0].predicted == pytest.approx(0.25)  # pyright: ignore[reportUnknownMemberType]

    @pytest.mark.asyncio
    async def test_scoped_call_finds_the_learners_own_latest_rating(self, db: AsyncSession) -> None:
        from sophia.services.athena_confidence import get_confidence_ratings

        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted, user_id) "
            "VALUES (?, ?, ?, ?)",
            ("Sorting", 42, 0.4, "learner"),
        )
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted, user_id) "
            "VALUES (?, ?, ?, ?)",
            ("Sorting", 42, 0.6, "other-learner"),
        )

        result = await get_confidence_ratings(db, course_id=42, user_id="learner")

        assert len(result) == 1
        assert result[0].predicted == pytest.approx(0.4)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# get_blind_spots
# ---------------------------------------------------------------------------


class TestGetBlindSpots:
    @pytest.mark.asyncio
    async def test_finds_overconfident_topics(self, db: AsyncSession) -> None:
        from sophia.services.athena_confidence import get_blind_spots

        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted, actual) "
            "VALUES (?, ?, ?, ?)",
            ("Sorting", 42, 0.9, 0.3),
        )
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted, actual) "
            "VALUES (?, ?, ?, ?)",
            ("Hashing", 42, 0.5, 0.5),
        )

        result = await get_blind_spots(db, course_id=42)
        assert len(result) == 1
        assert result[0].topic == "Sorting"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_actual(self, db: AsyncSession) -> None:
        from sophia.services.athena_confidence import get_blind_spots

        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.9),
        )

        result = await get_blind_spots(db, course_id=42)
        assert result == []


# ---------------------------------------------------------------------------
# format_calibration_feedback
# ---------------------------------------------------------------------------


class TestFormatCalibrationFeedback:
    def test_no_actual_score(self) -> None:
        from sophia.services.athena_confidence import format_calibration_feedback

        r = ConfidenceRating(topic="Trees", course_id=1, predicted=0.75)
        text = format_calibration_feedback(r)
        assert "Trees" in text
        assert "pending" in text

    def test_well_calibrated(self) -> None:
        from sophia.services.athena_confidence import format_calibration_feedback

        r = ConfidenceRating(topic="Trees", course_id=1, predicted=0.5, actual=0.55)
        text = format_calibration_feedback(r)
        assert "calibrated" in text.lower() or "✅" in text

    def test_large_overconfidence(self) -> None:
        from sophia.services.athena_confidence import format_calibration_feedback

        r = ConfidenceRating(topic="Trees", course_id=1, predicted=0.9, actual=0.3)
        text = format_calibration_feedback(r)
        assert "common pattern" in text.lower() or "learning opportunity" in text.lower()

    def test_slight_overconfidence(self) -> None:
        from sophia.services.athena_confidence import format_calibration_feedback

        r = ConfidenceRating(topic="Trees", course_id=1, predicted=0.7, actual=0.5)
        text = format_calibration_feedback(r)
        assert "slightly overconfident" in text.lower() or "targeted review" in text.lower()

    def test_large_underconfidence(self) -> None:
        from sophia.services.athena_confidence import format_calibration_feedback

        r = ConfidenceRating(topic="Trees", course_id=1, predicted=0.2, actual=0.8)
        text = format_calibration_feedback(r)
        assert "imposter" in text.lower() or "more than you think" in text.lower()

    def test_slight_underconfidence(self) -> None:
        from sophia.services.athena_confidence import format_calibration_feedback

        r = ConfidenceRating(topic="Trees", course_id=1, predicted=0.4, actual=0.55)
        text = format_calibration_feedback(r)
        assert "better at this" in text.lower() or "underconfident" in text.lower()


# ---------------------------------------------------------------------------
# update_actual_score
# ---------------------------------------------------------------------------


class TestUpdateActualScore:
    @pytest.mark.asyncio
    async def test_updates_most_recent_rating(self, db: AsyncSession) -> None:
        from sophia.services.athena_confidence import update_actual_score

        # Two ratings for same topic — update should hit the latest
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.25),
        )
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.75),
        )

        await update_actual_score(db, "Sorting", course_id=42, actual=0.6)

        cursor = await exec_sql(db, "SELECT predicted, actual FROM confidence_ratings ORDER BY id")
        rows = list(cursor.fetchall())
        assert len(rows) == 2
        # First rating should be untouched
        assert rows[0][1] is None
        # Second (latest) should be updated
        assert rows[1][1] == pytest.approx(0.6)  # pyright: ignore[reportUnknownMemberType]

    @pytest.mark.asyncio
    async def test_unscoped_call_never_touches_a_learners_owned_rating(
        self, db: AsyncSession
    ) -> None:
        """confidence_ratings mixes owner-less rows (the general calibration
        surfaces this predates) with per-learner ones (study realtime). An
        unscoped call — the legacy surfaces have no learner to pass — must
        stay restricted to owner-less rows, never the newest row overall,
        or a learner's own study-realtime prediction gets silently
        overwritten by someone else's legacy calibration PATCH."""
        from sophia.services.athena_confidence import update_actual_score

        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.25),
        )
        await exec_sql(
            db,
            "INSERT INTO confidence_ratings (topic, course_id, predicted, user_id) "
            "VALUES (?, ?, ?, ?)",
            ("Sorting", 42, 0.9, "learner"),
        )

        await update_actual_score(db, "Sorting", course_id=42, actual=0.6)

        cursor = await exec_sql(db, "SELECT user_id, actual FROM confidence_ratings ORDER BY id")
        rows = list(cursor.fetchall())
        assert rows[0][0] is None
        assert rows[0][1] == pytest.approx(0.6)  # pyright: ignore[reportUnknownMemberType]
        assert rows[1][0] == "learner"
        assert rows[1][1] is None
