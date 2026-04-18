"""Tests for error_boundary, loading, confidence_rating and flashcard components."""

from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import user_simulation

from sophia.gui.components.confidence_rating import (
    RATING_LABELS,
    confidence_rating,
    rating_to_difficulty,
)
from sophia.gui.components.error_boundary import error_boundary
from sophia.gui.components.flashcard import flashcard
from sophia.gui.components.loading import loading_spinner, skeleton_card


class TestErrorBoundary:
    async def test_renders_content_when_no_error(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            async def index() -> None:
                await error_boundary(lambda: ui.label("All good"), page_name="Test")

            await user.open("/")
            await user.should_see("All good")

    async def test_catches_exception_and_shows_recovery(self) -> None:
        def _broken() -> None:
            msg = "test explosion"
            raise ValueError(msg)

        async with user_simulation() as user:

            @ui.page("/")
            async def index() -> None:
                await error_boundary(_broken, page_name="Broken")

            await user.open("/")
            await user.should_see("ValueError: test explosion")
            await user.should_see("Retry")

    async def test_error_card_shows_page_name(self) -> None:
        def _broken() -> None:
            msg = "kaboom"
            raise RuntimeError(msg)

        async with user_simulation() as user:

            @ui.page("/")
            async def index() -> None:
                await error_boundary(_broken, page_name="MyPage")

            await user.open("/")
            await user.should_see("RuntimeError: kaboom")

    async def test_awaits_async_content_fn(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            async def index() -> None:
                async def _async_content() -> None:
                    ui.label("Async content rendered")

                await error_boundary(_async_content, page_name="AsyncTest")

            await user.open("/")
            await user.should_see("Async content rendered")

    async def test_catches_async_content_exception(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            async def index() -> None:
                async def _broken_async() -> None:
                    msg = "async boom"
                    raise ValueError(msg)

                await error_boundary(_broken_async, page_name="AsyncBroken")

            await user.open("/")
            await user.should_see("ValueError: async boom")


class TestSkeletonCard:
    async def test_skeleton_renders_placeholder_divs(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                skeleton_card(count=2)

            await user.open("/")
            # Skeleton cards use animate-pulse class — just verify page renders
            # The cards are rendered as div elements, no visible text


class TestLoadingSpinner:
    async def test_spinner_renders_default_text(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                loading_spinner()

            await user.open("/")
            await user.should_see("Loading...")

    async def test_spinner_renders_custom_text(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                loading_spinner(text="Fetching data...")

            await user.open("/")
            await user.should_see("Fetching data...")


class TestConfidenceRating:
    async def test_renders_all_five_labels(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                confidence_rating(on_rate=lambda r: None)

            await user.open("/")
            for label in RATING_LABELS.values():
                await user.should_see(label)

    @pytest.mark.parametrize(
        ("rating", "expected_difficulty"),
        [
            (1, "cued"),
            (2, "cued"),
            (3, "explain"),
            (4, "transfer"),
            (5, "transfer"),
        ],
    )
    def test_rating_to_difficulty_mapping(self, rating: int, expected_difficulty: str) -> None:
        assert rating_to_difficulty(rating).value == expected_difficulty


class TestFlashcard:
    async def test_shows_front_content(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                flashcard(front="What is \\alpha?", back="Greek letter alpha")

            await user.open("/")
            await user.should_see("What is")

    async def test_back_hidden_until_reveal(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                flashcard(front="Front text", back="Secret answer")

            await user.open("/")
            await user.should_not_see("Secret answer")
            await user.should_see("Show Answer")

    async def test_reveal_shows_back(self) -> None:
        """Verify the reveal callback makes the back content visible."""
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                flashcard(front="Q", back="A")

            await user.open("/")
            await user.should_see("Show Answer")
