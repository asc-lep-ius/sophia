"""Tests for error_boundary and loading components."""

from __future__ import annotations

from nicegui import ui
from nicegui.testing import user_simulation

from sophia.gui.components.error_boundary import error_boundary
from sophia.gui.components.loading import loading_spinner, skeleton_card


class TestErrorBoundary:
    async def test_renders_content_when_no_error(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                error_boundary(lambda: ui.label("All good"), page_name="Test")

            await user.open("/")
            await user.should_see("All good")
            await user.should_not_see("Something went wrong")

    async def test_catches_exception_and_shows_recovery(self) -> None:
        def _broken() -> None:
            msg = "test explosion"
            raise ValueError(msg)

        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                error_boundary(_broken, page_name="Broken")

            await user.open("/")
            await user.should_see("Something went wrong")
            await user.should_see("Retry")
            await user.should_see("Dashboard")

    async def test_error_card_shows_page_name(self) -> None:
        def _broken() -> None:
            msg = "kaboom"
            raise RuntimeError(msg)

        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                error_boundary(_broken, page_name="MyPage")

            await user.open("/")
            await user.should_see("MyPage")


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
