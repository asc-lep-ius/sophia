"""Tests for the review card component."""

from __future__ import annotations

from nicegui import ui
from nicegui.testing import user_simulation

from sophia.gui.components.review_card import review_card

_INTERVAL_PREVIEWS = {1: "< 1 day", 2: "1 day", 3: "3 days", 4: "7 days"}


def _noop_str(_text: str) -> None:
    pass


def _noop_int(_rating: int) -> None:
    pass


class TestReviewCardFront:
    """Front side always visible regardless of show_back."""

    async def test_front_visible(self) -> None:
        async with user_simulation() as user:

            @ui.page("/test-front")
            def page() -> None:
                review_card(
                    front="What is 2+2?",
                    back="4",
                    on_submit_recall=_noop_str,
                    on_rate=_noop_int,
                    interval_previews=_INTERVAL_PREVIEWS,
                )

            await user.open("/test-front")
            await user.should_see("What is 2+2?")

    async def test_question_label_visible(self) -> None:
        async with user_simulation() as user:

            @ui.page("/test-question-label")
            def page() -> None:
                review_card(
                    front="Define entropy",
                    back="Measure of disorder",
                    on_submit_recall=_noop_str,
                    on_rate=_noop_int,
                    interval_previews=_INTERVAL_PREVIEWS,
                )

            await user.open("/test-question-label")
            await user.should_see("Question")


class TestReviewCardRecallPhase:
    """When show_back=False, the recall text area is shown."""

    async def test_textarea_visible(self) -> None:
        async with user_simulation() as user:

            @ui.page("/test-textarea")
            def page() -> None:
                review_card(
                    front="What is 2+2?",
                    back="4",
                    on_submit_recall=_noop_str,
                    on_rate=_noop_int,
                    interval_previews=_INTERVAL_PREVIEWS,
                    show_back=False,
                )

            await user.open("/test-textarea")
            await user.should_see("Type your recall attempt")

    async def test_submit_button_visible(self) -> None:
        async with user_simulation() as user:

            @ui.page("/test-submit-btn")
            def page() -> None:
                review_card(
                    front="What is 2+2?",
                    back="4",
                    on_submit_recall=_noop_str,
                    on_rate=_noop_int,
                    interval_previews=_INTERVAL_PREVIEWS,
                    show_back=False,
                )

            await user.open("/test-submit-btn")
            await user.should_see("Submit")

    async def test_rating_buttons_not_visible(self) -> None:
        async with user_simulation() as user:

            @ui.page("/test-no-rating")
            def page() -> None:
                review_card(
                    front="What is 2+2?",
                    back="4",
                    on_submit_recall=_noop_str,
                    on_rate=_noop_int,
                    interval_previews=_INTERVAL_PREVIEWS,
                    show_back=False,
                )

            await user.open("/test-no-rating")
            await user.should_not_see("Again")
            await user.should_not_see("Easy")


class TestReviewCardAnswerPhase:
    """When show_back=True, the answer side is shown."""

    async def test_recall_text_visible(self) -> None:
        async with user_simulation() as user:

            @ui.page("/test-recall-text")
            def page() -> None:
                review_card(
                    front="What is 2+2?",
                    back="4",
                    on_submit_recall=_noop_str,
                    on_rate=_noop_int,
                    interval_previews=_INTERVAL_PREVIEWS,
                    show_back=True,
                    recall_text="four",
                )

            await user.open("/test-recall-text")
            await user.should_see("Your recall:")
            await user.should_see("four")

    async def test_answer_visible(self) -> None:
        async with user_simulation() as user:

            @ui.page("/test-answer")
            def page() -> None:
                review_card(
                    front="What is 2+2?",
                    back="4",
                    on_submit_recall=_noop_str,
                    on_rate=_noop_int,
                    interval_previews=_INTERVAL_PREVIEWS,
                    show_back=True,
                    recall_text="four",
                )

            await user.open("/test-answer")
            await user.should_see("Answer")
            await user.should_see("4")

    async def test_rating_buttons_visible_with_labels(self) -> None:
        async with user_simulation() as user:

            @ui.page("/test-rating-buttons")
            def page() -> None:
                review_card(
                    front="What is 2+2?",
                    back="4",
                    on_submit_recall=_noop_str,
                    on_rate=_noop_int,
                    interval_previews=_INTERVAL_PREVIEWS,
                    show_back=True,
                    recall_text="four",
                )

            await user.open("/test-rating-buttons")
            await user.should_see("Again (< 1 day)")
            await user.should_see("Hard (1 day)")
            await user.should_see("Good (3 days)")
            await user.should_see("Easy (7 days)")

    async def test_submit_button_not_visible(self) -> None:
        async with user_simulation() as user:

            @ui.page("/test-no-submit")
            def page() -> None:
                review_card(
                    front="What is 2+2?",
                    back="4",
                    on_submit_recall=_noop_str,
                    on_rate=_noop_int,
                    interval_previews=_INTERVAL_PREVIEWS,
                    show_back=True,
                    recall_text="four",
                )

            await user.open("/test-no-submit")
            await user.should_not_see("Submit")
