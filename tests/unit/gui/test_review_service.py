"""Tests for the review service GUI wrappers and pure helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from sophia.gui.services.review_service import (
    RATING_LABELS,
    RATING_SCORES,
    complete_review_item,
    compute_interval_previews,
    format_interval,
    get_due_review_items,
    get_upcoming_review_items,
    rating_to_score,
)

_PATCH_BASE = "sophia.gui.services.review_service"


# ---------------------------------------------------------------------------
# Pure function: format_interval
# ---------------------------------------------------------------------------


class TestFormatInterval:
    @pytest.mark.parametrize(
        ("days", "expected"),
        [
            (0, "< 1 day"),
            (1, "1 day"),
            (2, "2 days"),
            (7, "7 days"),
            (30, "30 days"),
            (365, "365 days"),
        ],
    )
    def test_format_interval(self, days: int, expected: str) -> None:
        assert format_interval(days) == expected


# ---------------------------------------------------------------------------
# Pure function: rating_to_score
# ---------------------------------------------------------------------------


class TestRatingToScore:
    @pytest.mark.parametrize(
        ("rating", "expected"),
        [
            (1, 0.0),
            (2, 0.3),
            (3, 0.7),
            (4, 1.0),
        ],
    )
    def test_valid_ratings(self, rating: int, expected: float) -> None:
        assert rating_to_score(rating) == expected

    @pytest.mark.parametrize("invalid_rating", [0, 5, -1, 100])
    def test_invalid_rating_raises(self, invalid_rating: int) -> None:
        with pytest.raises(ValueError, match="Rating must be 1–4"):
            rating_to_score(invalid_rating)


# ---------------------------------------------------------------------------
# Pure function: compute_interval_previews
# ---------------------------------------------------------------------------


class TestComputeIntervalPreviews:
    def test_returns_all_four_ratings(self) -> None:
        result = compute_interval_previews(difficulty=0.3, stability=1.0)
        assert set(result.keys()) == {1, 2, 3, 4}

    def test_values_are_formatted_strings(self) -> None:
        result = compute_interval_previews(difficulty=0.3, stability=1.0)
        for value in result.values():
            assert isinstance(value, str)

    def test_higher_ratings_produce_longer_intervals(self) -> None:
        """Easy should produce a longer (or equal) interval than Again."""
        from sophia.services.athena_review import compute_fsrs_interval

        _, _, days_again = compute_fsrs_interval(0.3, 5.0, RATING_SCORES[1])
        _, _, days_easy = compute_fsrs_interval(0.3, 5.0, RATING_SCORES[4])
        assert days_easy >= days_again

    def test_preview_uses_format_interval(self) -> None:
        """Each preview value should match format_interval of the computed days."""
        from sophia.services.athena_review import compute_fsrs_interval

        diff, stab = 0.3, 1.0
        result = compute_interval_previews(difficulty=diff, stability=stab)
        for rating in (1, 2, 3, 4):
            _, _, days = compute_fsrs_interval(diff, stab, RATING_SCORES[rating])
            assert result[rating] == format_interval(days)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_rating_labels(self) -> None:
        assert RATING_LABELS == {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}

    def test_rating_scores(self) -> None:
        assert RATING_SCORES == {1: 0.0, 2: 0.3, 3: 0.7, 4: 1.0}


# ---------------------------------------------------------------------------
# Async wrapper: get_due_review_items
# ---------------------------------------------------------------------------


class TestGetDueReviewItems:
    @pytest.mark.asyncio
    async def test_delegates_to_service(self, mock_container: AsyncMock) -> None:
        sentinel = [object()]
        with patch(f"{_PATCH_BASE}.athena_review") as mock_mod:
            mock_mod.get_due_reviews = AsyncMock(return_value=sentinel)
            result = await get_due_review_items(mock_container.db)
        mock_mod.get_due_reviews.assert_awaited_once_with(mock_container.db, course_id=None)
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_passes_course_id(self, mock_container: AsyncMock) -> None:
        with patch(f"{_PATCH_BASE}.athena_review") as mock_mod:
            mock_mod.get_due_reviews = AsyncMock(return_value=[])
            await get_due_review_items(mock_container.db, course_id=42)
        mock_mod.get_due_reviews.assert_awaited_once_with(mock_container.db, course_id=42)


# ---------------------------------------------------------------------------
# Async wrapper: complete_review_item
# ---------------------------------------------------------------------------


class TestCompleteReviewItem:
    @pytest.mark.asyncio
    async def test_delegates_to_service(self, mock_container: AsyncMock) -> None:
        sentinel = object()
        with patch(f"{_PATCH_BASE}.athena_review") as mock_mod:
            mock_mod.complete_review = AsyncMock(return_value=sentinel)
            result = await complete_review_item(
                mock_container.db, topic="Trees", course_id=1, score=0.7
            )
        mock_mod.complete_review.assert_awaited_once_with(
            mock_container.db, "Trees", 1, 0.7
        )
        assert result is sentinel


# ---------------------------------------------------------------------------
# Async wrapper: get_upcoming_review_items
# ---------------------------------------------------------------------------


class TestGetUpcomingReviewItems:
    @pytest.mark.asyncio
    async def test_delegates_to_service(self, mock_container: AsyncMock) -> None:
        sentinel = [object()]
        with patch(f"{_PATCH_BASE}.athena_review") as mock_mod:
            mock_mod.get_upcoming_reviews = AsyncMock(return_value=sentinel)
            result = await get_upcoming_review_items(mock_container.db)
        mock_mod.get_upcoming_reviews.assert_awaited_once_with(
            mock_container.db, course_id=None, days_ahead=3
        )
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_passes_all_kwargs(self, mock_container: AsyncMock) -> None:
        with patch(f"{_PATCH_BASE}.athena_review") as mock_mod:
            mock_mod.get_upcoming_reviews = AsyncMock(return_value=[])
            await get_upcoming_review_items(mock_container.db, course_id=5, days_ahead=7)
        mock_mod.get_upcoming_reviews.assert_awaited_once_with(
            mock_container.db, course_id=5, days_ahead=7
        )
