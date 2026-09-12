"""Where the legacy GUI sends a learner, and what it keeps serving.

Phase 4a (issue #99) moved dashboard, quickstart and review to SvelteKit,
phase 4b (issue #100) moved lectures and topics, and phase 4c (issue #101)
moved search, deadlines, calibration and registration. Two things have to stay
true together: nothing in this app sends anyone to its own copy of those pages any
more, and the pages themselves stay registered so a ``/legacy/`` link somebody
already has keeps resolving. Retiring them is phase 5's job.
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
    CALIBRATION_SURFACE_PATH,
    CHRONOS_SURFACE_PATH,
    CONTENT_SURFACE_PATH,
    DASHBOARD_SURFACE_PATH,
    QUICKSTART_SURFACE_PATH,
    REGISTER_SURFACE_PATH,
    REVIEW_SURFACE_PATH,
    SEARCH_SURFACE_PATH,
    STUDY_SURFACE_PATH,
    TOPICS_SURFACE_PATH,
)

if TYPE_CHECKING:
    from sophia.config import Settings

MIGRATED_SURFACES = (
    CALIBRATION_SURFACE_PATH,
    CHRONOS_SURFACE_PATH,
    CONTENT_SURFACE_PATH,
    DASHBOARD_SURFACE_PATH,
    QUICKSTART_SURFACE_PATH,
    REGISTER_SURFACE_PATH,
    REVIEW_SURFACE_PATH,
    SEARCH_SURFACE_PATH,
    STUDY_SURFACE_PATH,
    TOPICS_SURFACE_PATH,
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
        # Enumerated, not listed: a fifth constant added later has to be wired
        # up too, and a hardcoded list would let it through silently.
        constants = [name for name in dir(routes) if name.endswith("_SURFACE_PATH")]

        assert len(constants) == len(MIGRATED_SURFACES)
        for name in constants:
            assert name in sources, name

    def test_navigation_sends_the_learner_to_the_new_dashboard_and_review(self) -> None:
        paths = {item["path"] for item in NAV_ITEMS}

        assert DASHBOARD_SURFACE_PATH in paths
        assert REVIEW_SURFACE_PATH in paths
        # The NiceGUI originals, which the nav used to point at.
        assert "/" not in paths
        assert "/review" not in paths

    def test_navigation_sends_the_learner_to_the_new_lectures_and_topics(self) -> None:
        """Topics gains an entry it never had in this app.

        The NiceGUI ``/topics`` page was only ever reachable by typing the URL.
        A migrated surface with no way in is a redirect nobody made, which is
        exactly what ``test_every_surface_constant_is_used_by_production_code``
        was written to catch.
        """
        paths = {item["path"] for item in NAV_ITEMS}

        assert CONTENT_SURFACE_PATH in paths
        assert TOPICS_SURFACE_PATH in paths
        assert "/lectures" not in paths
        assert "/topics" not in paths

    def test_the_pipeline_wizard_is_not_repointed_at_the_upload_page(self) -> None:
        """``/lectures/setup`` configures Whisper and the LLM, not content.

        ``/app/content/sources`` wears the same name and does something else:
        it is where a content source arrives from. Sending the wizard's callers
        there would answer a question about GPU settings with an upload form.
        """
        settings_source = inspect.getsource(settings_page)

        assert 'ui.navigate.to("/lectures/setup")' in settings_source
        assert CONTENT_SURFACE_PATH not in settings_source

    def test_navigation_sends_the_learner_to_the_new_long_tail_pages(self) -> None:
        paths = {item["path"] for item in NAV_ITEMS}

        assert SEARCH_SURFACE_PATH in paths
        assert CHRONOS_SURFACE_PATH in paths
        assert CALIBRATION_SURFACE_PATH in paths
        assert REGISTER_SURFACE_PATH in paths
        # The NiceGUI originals, which the nav used to point at.
        assert "/search" not in paths
        assert "/chronos" not in paths
        assert "/calibration" not in paths
        assert "/register" not in paths

    def test_chronos_history_is_not_a_surface_constant(self) -> None:
        """There is nothing in this app to repoint at it.

        The legacy page rendered past deadlines inside ``/chronos`` rather than
        at a route of their own, so a ``CHRONOS_HISTORY_SURFACE_PATH`` here
        would be a constant no production code could use — which
        ``test_every_surface_constant_is_used_by_production_code`` would then
        fail on. ``/app/chronos`` links to the migrated history instead.
        """
        assert not hasattr(routes, "CHRONOS_HISTORY_SURFACE_PATH")

    def test_keyboard_shortcuts_follow_the_navigation(self) -> None:
        assert _NAV_ROUTES["1"] == DASHBOARD_SURFACE_PATH
        assert _NAV_ROUTES["3"] == REVIEW_SURFACE_PATH
        assert _NAV_ROUTES["4"] == SEARCH_SURFACE_PATH

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
        assert "/lectures" in route_paths
        assert "/topics" in route_paths
        assert "/search" in route_paths
        assert "/chronos" in route_paths
        assert "/calibration" in route_paths
        assert "/register" in route_paths
        # The pipeline wizard is not superseded at all, so it has to survive
        # phase 5 as well as this one.
        assert "/lectures/setup" in route_paths
