"""Tests for the review page module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from nicegui import ui
from nicegui.testing import user_simulation

from sophia.domain.models import ReviewSchedule

_PATCH_BASE = "sophia.gui.pages.review"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_reviews() -> list[ReviewSchedule]:
    now = datetime.now(UTC)
    return [
        ReviewSchedule(
            topic="Binary Search",
            course_id=1,
            next_review_at=(now - timedelta(days=1)).isoformat(),
            difficulty=0.3,
            stability=1.0,
        ),
        ReviewSchedule(
            topic="Sorting Algorithms",
            course_id=1,
            next_review_at=(now - timedelta(hours=2)).isoformat(),
            difficulty=0.5,
            stability=2.0,
        ),
        ReviewSchedule(
            topic="Graph Theory",
            course_id=1,
            next_review_at=(now - timedelta(hours=1)).isoformat(),
            difficulty=0.7,
            stability=5.0,
        ),
    ]


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestFormatRetention:
    def test_low_difficulty_gives_high_retention(self) -> None:
        from sophia.gui.pages.review import _format_retention

        assert _format_retention(0.0) == "100%"

    def test_max_difficulty_gives_zero_retention(self) -> None:
        from sophia.gui.pages.review import _format_retention

        assert _format_retention(1.0) == "0%"

    def test_mid_difficulty(self) -> None:
        from sophia.gui.pages.review import _format_retention

        assert _format_retention(0.3) == "70%"


class TestClampStabilityPct:
    def test_zero_stability(self) -> None:
        from sophia.gui.pages.review import _clamp_stability_pct

        assert _clamp_stability_pct(0.0) == 0.0

    def test_max_stability(self) -> None:
        from sophia.gui.pages.review import _clamp_stability_pct

        assert _clamp_stability_pct(365.0) == 100.0

    def test_over_max_is_clamped(self) -> None:
        from sophia.gui.pages.review import _clamp_stability_pct

        assert _clamp_stability_pct(500.0) == 100.0

    def test_mid_stability(self) -> None:
        from sophia.gui.pages.review import _clamp_stability_pct

        result = _clamp_stability_pct(182.5)
        assert abs(result - 50.0) < 0.1


# ---------------------------------------------------------------------------
# Rendering tests
# ---------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
class TestReviewContent:
    async def test_renders_header(self) -> None:
        from sophia.gui.pages.review import review_content

        async with user_simulation() as user:

            @ui.page("/test-review-header")
            async def page() -> None:
                await review_content()

            await user.open("/test-review-header")
            await user.should_see("Review")

    async def test_renders_without_crashing(self) -> None:
        """Page loads without error even when no DI container is registered."""
        from sophia.gui.pages.review import review_content

        async with user_simulation() as user:

            @ui.page("/test-review-nocrash")
            async def page() -> None:
                await review_content()

            await user.open("/test-review-nocrash")
            await user.should_see("Review")


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
class TestReviewEmptyState:
    async def test_empty_state_shows_all_caught_up(self) -> None:
        from sophia.gui.pages.review import _render_empty_state

        async with user_simulation() as user:

            @ui.page("/test-review-empty")
            def page() -> None:
                _render_empty_state()

            await user.open("/test-review-empty")
            await user.should_see("All caught up!")

    async def test_empty_state_has_dashboard_link(self) -> None:
        from sophia.gui.pages.review import _render_empty_state

        async with user_simulation() as user:

            @ui.page("/test-review-empty-link")
            def page() -> None:
                _render_empty_state()

            await user.open("/test-review-empty-link")
            await user.should_see("Dashboard")


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
class TestReviewSessionSummary:
    async def test_summary_shows_total_and_avg(self) -> None:
        from sophia.gui.pages.review import _render_session_summary

        async with user_simulation() as user:

            @ui.page("/test-review-summary")
            def page() -> None:
                _render_session_summary(total=5, scores=[0.7, 0.3, 1.0, 0.7, 0.0])

            await user.open("/test-review-summary")
            await user.should_see("Session Complete")
            await user.should_see("5")

    async def test_summary_has_dashboard_link(self) -> None:
        from sophia.gui.pages.review import _render_session_summary

        async with user_simulation() as user:

            @ui.page("/test-review-summary-link")
            def page() -> None:
                _render_session_summary(total=3, scores=[0.7, 0.7, 0.7])

            await user.open("/test-review-summary-link")
            await user.should_see("Dashboard")


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
class TestShowBackState:
    """show_back / recall_text must survive a _review_session.refresh() round-trip."""

    async def test_get_show_back_defaults_to_false(self) -> None:
        from sophia.gui.pages.review import _get_show_back

        async with user_simulation() as user:

            @ui.page("/test-show-back-default")
            async def page() -> None:
                await ui.context.client.connected()
                result = _get_show_back()
                ui.label(f"show_back={result}")

            await user.open("/test-show-back-default")
            await user.should_see("show_back=False")

    async def test_set_and_get_show_back(self) -> None:
        from sophia.gui.pages.review import _get_show_back, _set_show_back

        async with user_simulation() as user:

            @ui.page("/test-show-back-set")
            async def page() -> None:
                await ui.context.client.connected()
                _set_show_back(True)
                result = _get_show_back()
                ui.label(f"show_back={result}")

            await user.open("/test-show-back-set")
            await user.should_see("show_back=True")

    async def test_get_recall_text_defaults_to_empty(self) -> None:
        from sophia.gui.pages.review import _get_recall_text

        async with user_simulation() as user:

            @ui.page("/test-recall-default")
            async def page() -> None:
                await ui.context.client.connected()
                result = _get_recall_text()
                ui.label(f"recall=[{result}]")

            await user.open("/test-recall-default")
            await user.should_see("recall=[]")

    async def test_set_and_get_recall_text(self) -> None:
        from sophia.gui.pages.review import _get_recall_text, _set_recall_text

        async with user_simulation() as user:

            @ui.page("/test-recall-set")
            async def page() -> None:
                await ui.context.client.connected()
                _set_recall_text("my answer")
                result = _get_recall_text()
                ui.label(f"recall=[{result}]")

            await user.open("/test-recall-set")
            await user.should_see("recall=[my answer]")

    async def test_reset_session_clears_show_back_and_recall(self) -> None:
        from sophia.gui.pages.review import (
            _get_recall_text,
            _get_show_back,
            _reset_session_state,
            _set_recall_text,
            _set_show_back,
        )

        async with user_simulation() as user:

            @ui.page("/test-reset-clears")
            async def page() -> None:
                await ui.context.client.connected()
                _set_show_back(True)
                _set_recall_text("answer")
                _reset_session_state()
                ui.label(f"show_back={_get_show_back()}")
                ui.label(f"recall=[{_get_recall_text()}]")

            await user.open("/test-reset-clears")
            await user.should_see("show_back=False")
            await user.should_see("recall=[]")


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
class TestReviewCardStats:
    async def test_renders_difficulty_bar(self) -> None:
        from sophia.gui.pages.review import _render_card_stats

        async with user_simulation() as user:

            @ui.page("/test-card-stats-diff")
            def page() -> None:
                _render_card_stats(difficulty=0.3, stability=10.0)

            await user.open("/test-card-stats-diff")
            await user.should_see("Difficulty")

    async def test_renders_stability_bar(self) -> None:
        from sophia.gui.pages.review import _render_card_stats

        async with user_simulation() as user:

            @ui.page("/test-card-stats-stab")
            def page() -> None:
                _render_card_stats(difficulty=0.3, stability=10.0)

            await user.open("/test-card-stats-stab")
            await user.should_see("Stability")

    async def test_renders_retention(self) -> None:
        from sophia.gui.pages.review import _render_card_stats

        async with user_simulation() as user:

            @ui.page("/test-card-stats-ret")
            def page() -> None:
                _render_card_stats(difficulty=0.3, stability=10.0)

            await user.open("/test-card-stats-ret")
            await user.should_see("70%")
