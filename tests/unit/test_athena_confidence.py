"""Tests for the Athena confidence service — confidence-before-reveal metacognitive workflow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pytest

from sophia.domain.models import ConfidenceRating


@pytest.fixture
async def db():
    """In-memory SQLite with topic + confidence migrations applied."""
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.executescript(Path("src/sophia/infra/migrations/006_topics.sql").read_text())
    await conn.executescript(Path("src/sophia/infra/migrations/007_confidence.sql").read_text())
    await conn.commit()
    yield conn
    await conn.close()


@pytest.fixture
def app_container(db: aiosqlite.Connection) -> MagicMock:
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
        assert r.calibration_error == pytest.approx(0.25)

    def test_calibration_error_underconfident(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.25, actual=0.75)
        assert r.calibration_error == pytest.approx(-0.5)

    def test_calibration_error_perfect(self) -> None:
        r = ConfidenceRating(topic="X", course_id=1, predicted=0.5, actual=0.5)
        assert r.calibration_error == pytest.approx(0.0)

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

        assert rating_to_score(rating) == pytest.approx(expected)

    def test_clamps_below_minimum(self) -> None:
        from sophia.services.athena_confidence import rating_to_score

        assert rating_to_score(0) == pytest.approx(0.0)
        assert rating_to_score(-5) == pytest.approx(0.0)

    def test_clamps_above_maximum(self) -> None:
        from sophia.services.athena_confidence import rating_to_score

        assert rating_to_score(6) == pytest.approx(1.0)
        assert rating_to_score(100) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# rate_confidence
# ---------------------------------------------------------------------------


class TestRateConfidence:
    @pytest.mark.asyncio
    async def test_stores_and_returns_rating(self, app_container: MagicMock) -> None:
        from sophia.services.athena_confidence import rate_confidence

        result = await rate_confidence(app_container, "Sorting", course_id=42, rating=4)

        assert isinstance(result, ConfidenceRating)
        assert result.topic == "Sorting"
        assert result.course_id == 42
        assert result.predicted == pytest.approx(0.75)
        assert result.actual is None
        assert result.rated_at != ""

    @pytest.mark.asyncio
    async def test_persists_to_database(
        self, app_container: MagicMock, db: aiosqlite.Connection
    ) -> None:
        from sophia.services.athena_confidence import rate_confidence

        await rate_confidence(app_container, "Hashing", course_id=42, rating=2)

        cursor = await db.execute("SELECT topic, predicted FROM confidence_ratings")
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "Hashing"
        assert rows[0][1] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# get_confidence_ratings
# ---------------------------------------------------------------------------


class TestGetConfidenceRatings:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_data(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_confidence import get_confidence_ratings

        result = await get_confidence_ratings(db, course_id=99)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_latest_per_topic(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_confidence import get_confidence_ratings

        # Insert two ratings for same topic — second should win
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.25),
        )
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.75),
        )
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Hashing", 42, 0.5),
        )
        await db.commit()

        result = await get_confidence_ratings(db, course_id=42)
        assert len(result) == 2

        by_topic = {r.topic: r for r in result}
        assert by_topic["Sorting"].predicted == pytest.approx(0.75)
        assert by_topic["Hashing"].predicted == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_filters_by_course_id(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_confidence import get_confidence_ratings

        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.5),
        )
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 99, 0.75),
        )
        await db.commit()

        result = await get_confidence_ratings(db, course_id=42)
        assert len(result) == 1
        assert result[0].course_id == 42


# ---------------------------------------------------------------------------
# get_blind_spots
# ---------------------------------------------------------------------------


class TestGetBlindSpots:
    @pytest.mark.asyncio
    async def test_finds_overconfident_topics(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_confidence import get_blind_spots

        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted, actual) "
            "VALUES (?, ?, ?, ?)",
            ("Sorting", 42, 0.9, 0.3),
        )
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted, actual) "
            "VALUES (?, ?, ?, ?)",
            ("Hashing", 42, 0.5, 0.5),
        )
        await db.commit()

        result = await get_blind_spots(db, course_id=42)
        assert len(result) == 1
        assert result[0].topic == "Sorting"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_actual(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_confidence import get_blind_spots

        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.9),
        )
        await db.commit()

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
    async def test_updates_most_recent_rating(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_confidence import update_actual_score

        # Two ratings for same topic — update should hit the latest
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.25),
        )
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
            ("Sorting", 42, 0.75),
        )
        await db.commit()

        await update_actual_score(db, "Sorting", course_id=42, actual=0.6)

        cursor = await db.execute("SELECT predicted, actual FROM confidence_ratings ORDER BY id")
        rows = await cursor.fetchall()
        assert len(rows) == 2
        # First rating should be untouched
        assert rows[0][1] is None
        # Second (latest) should be updated
        assert rows[1][1] == pytest.approx(0.6)
