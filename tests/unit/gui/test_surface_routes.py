"""Where the legacy GUI sends a learner, and what it keeps serving.

Phase 4a (issue #99) moved dashboard, quickstart and review to SvelteKit. Two
things have to stay true together: nothing in this app sends anyone to its own
copy of those pages any more, and the pages themselves stay registered so a
``/legacy/`` link somebody already has keeps resolving. Retiring them is phase
5's job.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.routing import Mount, Route, WebSocketRoute

from sophia.gui import routes
from sophia.gui.components.keyboard_shortcuts import _NAV_ROUTES
from sophia.gui.layout import NAV_ITEMS
from sophia.gui.pages import dashboard as dashboard_page
from sophia.gui.pages import review as review_page
from sophia.gui.pages import settings as settings_page
from sophia.gui.routes import (
    DASHBOARD_SURFACE_PATH,
    QUICKSTART_SURFACE_PATH,
    REVIEW_SURFACE_PATH,
    STUDY_SURFACE_PATH,
)

if TYPE_CHECKING:
    from sophia.config import Settings

MIGRATED_SURFACES = (
    DASHBOARD_SURFACE_PATH,
    QUICKSTART_SURFACE_PATH,
    REVIEW_SURFACE_PATH,
    STUDY_SURFACE_PATH,
)


def _route_paths() -> set[str]:
    from nicegui import app

    return {route.path for route in app.routes if isinstance(route, Route | Mount | WebSocketRoute)}


class TestMigratedSurfacePaths:
    def test_every_migrated_surface_points_under_app(self) -> None:
        for path in MIGRATED_SURFACES:
            assert path.startswith("/app/")

    def test_every_surface_constant_is_used_by_production_code(self) -> None:
        """A constant only the tests reference is a redirect nobody made.

        ``QUICKSTART_SURFACE_PATH`` was defined a phase before anything
        navigated to it, which read as done and was not.
        """
        sources = "".join(
            path.read_text(encoding="utf-8")
            for path in (Path(inspect.getfile(routes)).parent).rglob("*.py")
            if path.name != "routes.py"
        )

        for name in ("DASHBOARD_SURFACE_PATH", "QUICKSTART_SURFACE_PATH"):
            assert name in sources, name
        assert "REVIEW_SURFACE_PATH" in sources
        assert "STUDY_SURFACE_PATH" in sources

    def test_navigation_sends_the_learner_to_the_new_dashboard_and_review(self) -> None:
        paths = {item["path"] for item in NAV_ITEMS}

        assert DASHBOARD_SURFACE_PATH in paths
        assert REVIEW_SURFACE_PATH in paths
        # The NiceGUI originals, which the nav used to point at.
        assert "/" not in paths
        assert "/review" not in paths

    def test_keyboard_shortcuts_follow_the_navigation(self) -> None:
        assert _NAV_ROUTES["1"] == DASHBOARD_SURFACE_PATH
        assert _NAV_ROUTES["3"] == REVIEW_SURFACE_PATH

    def test_in_page_calls_to_action_leave_this_app_too(self) -> None:
        """A repointed sidebar is no use if the buttons inside the page are not.

        Read from the source rather than by rendering: these are lambdas inside
        NiceGUI builders, and the assertion is about which constant they close
        over, not about what the page looks like.
        """
        dashboard_source = inspect.getsource(dashboard_page)
        review_source = inspect.getsource(review_page)
        settings_source = inspect.getsource(settings_page)

        assert 'ui.navigate.to("/review")' not in dashboard_source
        assert "REVIEW_SURFACE_PATH" in dashboard_source
        assert 'ui.link("Dashboard", "/")' not in review_source
        assert 'ui.navigate.to("/")' not in review_source
        assert "DASHBOARD_SURFACE_PATH" in review_source
        # Settings' "Re-run Quickstart" is the wizard's only entry point that
        # is not the legacy dashboard's auto-opening modal.
        assert 'ui.navigate.to("/")' not in settings_source
        assert "QUICKSTART_SURFACE_PATH" in settings_source


class TestLegacyPagesStayReachable:
    def test_the_migrated_pages_are_still_served(self, mock_settings: Settings) -> None:
        """``/legacy/`` and ``/legacy/review`` must keep resolving.

        The proxy strips the ``/legacy`` prefix before this app sees the
        request, so what has to exist here is ``/`` and ``/review``. Deleting
        either is a phase 5 decision, and this test is what makes it one.
        """
        from sophia.gui.app import configure

        configure(mock_settings)
        route_paths = _route_paths()

        assert "/" in route_paths
        assert "/review" in route_paths
