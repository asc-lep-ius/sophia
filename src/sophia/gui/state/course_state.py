"""Course selection tab-storage accessor functions.

Provides per-tab course isolation with user-storage fallback so that
each browser tab can work with an independent course while new tabs
auto-select the last used course.
"""

from __future__ import annotations

from nicegui import app

from sophia.gui.state.storage_map import TAB_CURRENT_COURSE, USER_CURRENT_COURSE


def get_current_course() -> int | None:
    """Return the active course for the current tab.

    Reads tab storage first (per-tab isolation), then falls back to
    user storage (last used course across tabs).  Returns ``None`` if
    no course is selected in either tier.
    """
    tab_course = app.storage.tab.get(TAB_CURRENT_COURSE)
    if tab_course is not None:
        return tab_course
    return app.storage.user.get(USER_CURRENT_COURSE)


def set_current_course(course_id: int) -> None:
    """Set the active course in both tab and user storage."""
    app.storage.tab[TAB_CURRENT_COURSE] = course_id
    app.storage.user[USER_CURRENT_COURSE] = course_id


def init_course_for_tab() -> None:
    """Populate tab storage from user storage if not already set.

    Call during page load so new tabs auto-select the last used course
    without requiring a trip to the Dashboard.
    """
    if app.storage.tab.get(TAB_CURRENT_COURSE) is None:
        user_course = app.storage.user.get(USER_CURRENT_COURSE)
        if user_course is not None:
            app.storage.tab[TAB_CURRENT_COURSE] = user_course
