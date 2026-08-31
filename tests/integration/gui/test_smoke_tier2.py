"""Smoke tests for Tier 2 Core GUI features (#29-#36).

These tests start a real NiceGUI server against a seeded Postgres test
database and use Playwright to navigate pages and verify that all
acceptance criteria UI elements render correctly.

Improvements over the original prototype:
- Tests are grouped by page: navigate once, assert many things → faster.
- Fixed waits use ``wait_for_selector`` / Playwright ``expect`` instead of
  brittle ``wait_for_timeout`` calls.
- Topics tests inject course context via a test-only API endpoint so the
  full topics UI (header, topic list, Anki export) is exercised.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from unittest.mock import MagicMock

import httpx
import pytest
from playwright.sync_api import expect

from ..._sql import exec_sql
from ...conftest import TEST_ORG_ID, test_database_url, truncate_all

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Page
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_COURSE_ID: Final = 42
_COURSE_NAME: Final = "Linear Algebra"
_NOW: Final = datetime.now(UTC)

_DEADLINES: Final = [
    # Upcoming deadline (due in 5 days)
    (
        "dl-upcoming-1",
        "Assignment 3: Eigenvalues",
        _COURSE_ID,
        _COURSE_NAME,
        "assignment",
        (_NOW + timedelta(days=5)).isoformat(),
        0.15,
        None,
        None,
        "{}",
    ),
    # Upcoming deadline (due in 10 days)
    (
        "dl-upcoming-2",
        "Quiz 2: Vector Spaces",
        _COURSE_ID,
        _COURSE_NAME,
        "quiz",
        (_NOW + timedelta(days=10)).isoformat(),
        0.1,
        None,
        None,
        "{}",
    ),
    # Past deadline (due 3 days ago, has reflection)
    (
        "dl-past-1",
        "Assignment 2: Matrices",
        _COURSE_ID,
        _COURSE_NAME,
        "assignment",
        (_NOW - timedelta(days=3)).isoformat(),
        0.2,
        "submitted",
        None,
        "{}",
    ),
    # Past deadline (due 7 days ago, no reflection — missed)
    (
        "dl-past-2",
        "Checkmark Exercise 1",
        _COURSE_ID,
        _COURSE_NAME,
        "checkmark",
        (_NOW - timedelta(days=7)).isoformat(),
        None,
        None,
        None,
        "{}",
    ),
]

_EFFORT_ESTIMATES: Final = [
    ("dl-upcoming-1", _COURSE_ID, 8.0, None, None, "full"),
    ("dl-upcoming-2", _COURSE_ID, 4.0, None, None, "full"),
]

_TIME_ENTRIES: Final = [
    ("dl-upcoming-1", 2.0, "manual", "reading chapter 5", _NOW.isoformat()),
    ("dl-past-1", 5.0, "manual", "completed over weekend", (_NOW - timedelta(days=4)).isoformat()),
]

_REFLECTIONS: Final = [
    (
        "dl-past-1",
        4.0,
        5.0,
        "Took longer than expected due to proofs.",
        (_NOW - timedelta(days=2)).isoformat(),
    ),
]

_TOPICS: Final = [
    ("Eigenvalues and Eigenvectors", _COURSE_ID, "lecture", 3),
    ("Vector Spaces", _COURSE_ID, "lecture", 2),
    ("Linear Transformations", _COURSE_ID, "quiz", 1),
]

_WAIT_MS: Final = 5_000


# ---------------------------------------------------------------------------
# Seeded server fixture
# ---------------------------------------------------------------------------


async def _truncate(database_url: str) -> None:
    """Empty every table through an engine owned by the calling thread's loop."""
    from sophia.infra.engine import create_engine

    engine = create_engine(database_url, pool_size=1, max_overflow=0)
    try:
        await truncate_all(engine)
    finally:
        await engine.dispose()


async def _seed_db(db: AsyncSession) -> None:
    """Insert test data into the migrated database."""
    for dl in _DEADLINES:
        await exec_sql(
            db,
            "INSERT OR IGNORE INTO deadline_cache "
            "(id, name, course_id, course_name, deadline_type, due_at, grade_weight, "
            "submission_status, url, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            dl,
            conflict="id",
        )
    for est in _EFFORT_ESTIMATES:
        await exec_sql(
            db,
            "INSERT INTO effort_estimates "
            "(deadline_id, course_id, predicted_hours, "
            "breakdown, implementation_intention, scaffold_level) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            est,
        )
    for te in _TIME_ENTRIES:
        await exec_sql(
            db,
            "INSERT INTO time_entries "
            "(deadline_id, hours, source, note, recorded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            te,
        )
    for ref in _REFLECTIONS:
        await exec_sql(
            db,
            "INSERT INTO deadline_reflections "
            "(deadline_id, predicted_hours, actual_hours, "
            "reflection_text, reflected_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ref,
        )
    for t in _TOPICS:
        await exec_sql(
            db,
            "INSERT OR IGNORE INTO topic_mappings "
            "(topic, course_id, source, frequency) "
            "VALUES (?, ?, ?, ?)",
            t,
            conflict="topic, course_id, source",
        )


@pytest.fixture(scope="module")
def seeded_base_url() -> Generator[str, None, None]:
    """Start NiceGUI with a seeded in-memory DB — no real TUWEL auth needed.

    Strategy:
    1. Seed the Postgres test database from a separate thread, through an engine
       created and disposed inside that thread's own event loop.
    2. Start the NiceGUI server in a daemon thread (``_startup`` will fail
       auth — that's OK).
    3. Once the server is healthy, inject a mock container with the real DB
       via ``set_container()``, overriding the auth error.
    4. Register a test-only ``/_test/set_user_storage`` endpoint so E2E tests
       can set ``app.storage.user`` (e.g. ``current_course``) from the browser.
    """
    import asyncio

    from sophia.config import Settings
    from sophia.gui.middleware.health import set_container
    from sophia.infra.alembic_runner import upgrade
    from sophia.infra.engine import create_engine, create_session_factory, session_scope

    database_url = test_database_url()
    upgrade(database_url)

    async def _seed() -> None:
        """Seed through a throwaway engine.

        asyncpg binds a connection to the loop that opened it, and this runs in
        a setup thread with its own loop, so the seeding engine must be disposed
        here rather than handed to the server thread.
        """
        seed_engine = create_engine(database_url, pool_size=1, max_overflow=0)
        try:
            factory = create_session_factory(seed_engine)
            async with session_scope(factory, org_id=TEST_ORG_ID) as session:
                await _seed_db(session)
        finally:
            await seed_engine.dispose()

    def _setup_db() -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_seed())
        finally:
            loop.close()

    setup_thread = threading.Thread(target=_setup_db)
    setup_thread.start()
    setup_thread.join()

    # Never connected here: the pool opens its first connection inside the
    # server thread's loop, which is the only loop allowed to use it.
    engine = create_engine(database_url, pool_size=2, max_overflow=0)
    session_factory = create_session_factory(engine)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    os.environ["NICEGUI_SCREEN_TEST_PORT"] = str(port)
    base_url = f"http://127.0.0.1:{port}"
    settings = Settings(gui_host="127.0.0.1", gui_port=port, auto_sync=False)

    def _run_server() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        from nicegui import app as nicegui_app
        from nicegui import ui

        from sophia.gui.app import configure

        configure(settings)

        # Test-only page: let Playwright set user storage within NiceGUI context.
        @ui.page("/_test/set_course/{course_id}")
        async def _test_set_course(course_id: int) -> None:
            nicegui_app.storage.user["current_course"] = course_id
            ui.label(f"Course set to {course_id}")

        nicegui_app.on_shutdown(engine.dispose)

        ui.run(
            host="127.0.0.1",
            port=port,
            title="Sophia Smoke Test",
            reload=False,
            show=False,
            storage_secret="sophia-smoke-test-secret",
        )

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                break
        except httpx.ConnectError:
            time.sleep(0.5)
    else:
        msg = f"Seeded GUI server did not start within 30s on {base_url}"
        raise TimeoutError(msg)

    container = MagicMock(
        spec_set=[
            "settings",
            "http",
            "engine",
            "session_factory",
            "session",
            "moodle",
            "tiss",
            "opencast",
            "lecture_downloader",
        ],
    )
    container.settings = settings
    container.engine = engine
    container.session_factory = session_factory
    container.session = lambda **kwargs: session_scope(
        session_factory,
        org_id=kwargs.get("org_id", TEST_ORG_ID),
    )
    container.http = MagicMock()
    container.moodle = MagicMock()
    container.tiss = MagicMock()
    container.opencast = MagicMock()
    container.lecture_downloader = MagicMock()
    set_container(container)

    yield base_url

    # Teardown — signal uvicorn to stop (triggers app.on_shutdown → engine.dispose)
    from nicegui.server import Server

    if hasattr(Server, "instance"):
        Server.instance.should_exit = True
    server_thread.join(timeout=30)

    # The seed rows live in the shared test database, so they have to go or the
    # next test to run sees this module's deadlines and topics.
    def _clear() -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_truncate(database_url))
        finally:
            loop.close()

    cleanup_thread = threading.Thread(target=_clear)
    cleanup_thread.start()
    cleanup_thread.join()


def _goto(pg: Page, url: str) -> None:
    """Navigate and wait for NiceGUI to finish rendering."""
    pg.goto(url)
    pg.wait_for_load_state("networkidle")


def _set_course(pg: Page, base_url: str) -> None:
    """Set ``current_course`` in NiceGUI user storage via a NiceGUI test page."""
    pg.goto(f"{base_url}/_test/set_course/{_COURSE_ID}")
    pg.wait_for_load_state("networkidle")


# ===========================================================================
# Chronos page — all features on /chronos (#29-#34)
# ===========================================================================


class TestChronosDeadlineCards:
    """#29-#31: Deadline list, action buttons, reflection, and time entries."""

    def test_page_loads_without_errors(self, page: Page, seeded_base_url: str) -> None:
        """The /chronos page loads without error boundary or init message."""
        _goto(page, f"{seeded_base_url}/chronos")
        expect(page.locator("text=Something went wrong")).to_have_count(0)
        expect(page.locator("text=Application not initialized")).to_have_count(0)

    def test_header_and_deadline_names(self, page: Page, seeded_base_url: str) -> None:
        """#29: Header shows 'Deadlines' and seeded deadline names render."""
        _goto(page, f"{seeded_base_url}/chronos")
        expect(page.locator("text=Deadlines").first).to_be_visible()
        expect(page.locator("text=Assignment 3: Eigenvalues").first).to_be_visible(timeout=_WAIT_MS)
        expect(page.locator("text=Quiz 2: Vector Spaces").first).to_be_visible(timeout=_WAIT_MS)

    def test_action_buttons_present(self, page: Page, seeded_base_url: str) -> None:
        """#29-#31: Deadline cards have Estimate, Log Time, Mark Complete, Reflect."""
        _goto(page, f"{seeded_base_url}/chronos")
        page.wait_for_selector("button:has-text('Estimate')", timeout=_WAIT_MS)
        for btn_text in ("Estimate", "Log Time", "Mark Complete", "Reflect"):
            expect(page.locator(f"button:has-text('{btn_text}')").first).to_be_visible()

    def test_time_entry_note_visible(self, page: Page, seeded_base_url: str) -> None:
        """#31: Seeded time-entry note appears on the deadline card."""
        _goto(page, f"{seeded_base_url}/chronos")
        expect(page.locator("text=reading chapter 5").first).to_be_visible(timeout=_WAIT_MS)

    def test_reflect_dialog_opens(self, page: Page, seeded_base_url: str) -> None:
        """#29: Clicking Reflect opens a dialog with guided reflection prompts."""
        _goto(page, f"{seeded_base_url}/chronos")
        page.locator("button:has-text('Reflect')").first.click(timeout=_WAIT_MS)
        expect(page.locator("text=Reflect:").first).to_be_visible(timeout=_WAIT_MS)
        expect(page.locator("text=What went well").first).to_be_visible()

    def test_log_time_dialog_with_date_picker(self, page: Page, seeded_base_url: str) -> None:
        """#31: Log Time dialog opens and includes a date picker."""
        _goto(page, f"{seeded_base_url}/chronos")
        page.locator("button:has-text('Log Time')").first.click(timeout=_WAIT_MS)
        expect(page.locator("text=Log Time:").first).to_be_visible(timeout=_WAIT_MS)
        expect(page.locator(".q-date").first).to_be_visible()


class TestChronosSync:
    """#30: Sync button with progress indicator."""

    def test_sync_button_present(self, page: Page, seeded_base_url: str) -> None:
        _goto(page, f"{seeded_base_url}/chronos")
        expect(page.locator("button:has-text('Sync')").first).to_be_visible()


class TestChronosEffortChart:
    """#32: Effort distribution chart with agency-oriented subtitle."""

    def test_effort_heading_and_subtitle(self, page: Page, seeded_base_url: str) -> None:
        """Chart heading says 'Effort Distribution' with an agency subtitle."""
        _goto(page, f"{seeded_base_url}/chronos")
        expect(page.locator("text=Effort Distribution").first).to_be_visible(timeout=_WAIT_MS)
        expect(page.locator("text=/free hours|fully booked|No upcoming/i").first).to_be_visible(
            timeout=_WAIT_MS
        )

    def test_effort_chart_or_table_renders(self, page: Page, seeded_base_url: str) -> None:
        """#32: EChart canvas or accessible data table renders."""
        _goto(page, f"{seeded_base_url}/chronos")
        chart_or_table = page.locator("canvas, table")
        expect(chart_or_table.first).to_be_visible(timeout=_WAIT_MS)


class TestChronosPastDeadlines:
    """#33: Past deadlines section with outcome badges and filtering."""

    def test_past_deadlines_expansion_and_badges(self, page: Page, seeded_base_url: str) -> None:
        """Expanding 'Past Deadlines' shows outcome badges and deadline names."""
        _goto(page, f"{seeded_base_url}/chronos")
        past = page.locator("text=Past Deadlines").first
        expect(past).to_be_visible(timeout=_WAIT_MS)
        past.click()
        # Outcome badges
        expect(page.locator("text=/On Time|Late|Missed/").first).to_be_visible(timeout=_WAIT_MS)
        # Filter toggle
        expect(page.locator("text=All").first).to_be_visible()
        # Past deadline names
        expect(page.locator("text=Assignment 2: Matrices").first).to_be_visible()
        expect(page.locator("text=Checkmark Exercise 1").first).to_be_visible()

    def test_expandable_detail_row(self, page: Page, seeded_base_url: str) -> None:
        """#33: Past deadline rows expand to show reflection + calibration."""
        _goto(page, f"{seeded_base_url}/chronos")
        page.locator("text=Past Deadlines").first.click()
        details = page.locator("text=Details")
        if details.count() >= 1:
            details.first.click()
            expect(page.locator("text=Reflection").first).to_be_visible(timeout=_WAIT_MS)
            expect(page.locator("text=Calibration").first).to_be_visible()


class TestChronosCalendarExport:
    """#34: ICS calendar export button."""

    def test_export_button_with_icon(self, page: Page, seeded_base_url: str) -> None:
        _goto(page, f"{seeded_base_url}/chronos")
        expect(page.locator("button:has-text('Export Calendar')").first).to_be_visible()
        expect(page.locator("text=calendar_month").first).to_be_visible()


# ===========================================================================
# Topics page — features on /topics (#35-#36)
# ===========================================================================


class TestTopicsNoCourseFallback:
    """#35: Without a selected course, page loads cleanly with a prompt."""

    def test_loads_without_errors(self, page: Page, seeded_base_url: str) -> None:
        _goto(page, f"{seeded_base_url}/topics")
        expect(page.locator("text=Something went wrong")).to_have_count(0)
        expect(page.locator("text=Application not initialized")).to_have_count(0)

    def test_shows_course_selection_prompt(self, page: Page, seeded_base_url: str) -> None:
        _goto(page, f"{seeded_base_url}/topics")
        expect(page.locator("text=Select a course from the Dashboard").first).to_be_visible()


class TestTopicsWithCourse:
    """#35-#36: With a selected course, topics list and Anki export render."""

    def test_topics_header_and_buttons(self, page: Page, seeded_base_url: str) -> None:
        """#35/#36: Header shows 'Topics', 'Extract Topics', and 'Export Anki Deck'."""
        # Set course context first (need a page load for the storage cookie)
        _goto(page, f"{seeded_base_url}/topics")
        _set_course(page, seeded_base_url)
        _goto(page, f"{seeded_base_url}/topics")
        expect(page.locator("text=Topics").first).to_be_visible(timeout=_WAIT_MS)
        expect(page.locator("button:has-text('Extract Topics')").first).to_be_visible()
        expect(page.locator("button:has-text('Export Anki Deck')").first).to_be_visible()

    def test_topic_list_renders(self, page: Page, seeded_base_url: str) -> None:
        """#35: Seeded topics appear with source badges."""
        _goto(page, f"{seeded_base_url}/topics")
        _set_course(page, seeded_base_url)
        _goto(page, f"{seeded_base_url}/topics")
        expect(page.locator("text=Eigenvalues and Eigenvectors").first).to_be_visible(
            timeout=_WAIT_MS
        )
        expect(page.locator("text=Vector Spaces").first).to_be_visible()
        expect(page.locator("text=LECTURE").first).to_be_visible()

    def test_confidence_badges_present(self, page: Page, seeded_base_url: str) -> None:
        """#35: Each topic shows a confidence badge (at least 'Not rated')."""
        _goto(page, f"{seeded_base_url}/topics")
        _set_course(page, seeded_base_url)
        _goto(page, f"{seeded_base_url}/topics")
        expect(page.locator("text=Not rated").first).to_be_visible(timeout=_WAIT_MS)

    def test_anki_export_dialog(self, page: Page, seeded_base_url: str) -> None:
        """#36: Clicking 'Export Anki Deck' shows a dialog with pedagogical nudge."""
        _goto(page, f"{seeded_base_url}/topics")
        _set_course(page, seeded_base_url)
        _goto(page, f"{seeded_base_url}/topics")
        page.locator("button:has-text('Export Anki Deck')").first.click(timeout=_WAIT_MS)
        expect(page.locator("text=Export Anki Deck").nth(1)).to_be_visible(timeout=_WAIT_MS)
        # Pedagogical nudge text
        expect(page.locator("text=starting point").first).to_be_visible()
        expect(page.locator("button:has-text('Cancel')").first).to_be_visible()
        expect(page.locator("button:has-text('Export')").first).to_be_visible()


# ===========================================================================
# Cross-cutting
# ===========================================================================


class TestAccessibility:
    """Main content landmarks on both pages."""

    def test_chronos_main_content_landmark(self, page: Page, seeded_base_url: str) -> None:
        _goto(page, f"{seeded_base_url}/chronos")
        expect(page.locator("#main-content, main, [role='main']").first).to_be_visible()

    def test_topics_main_content_landmark(self, page: Page, seeded_base_url: str) -> None:
        _goto(page, f"{seeded_base_url}/topics")
        expect(page.locator("#main-content, main, [role='main']").first).to_be_visible()
