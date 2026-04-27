"""Tests for course_state accessor functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sophia.gui.state.storage_map import TAB_CURRENT_COURSE, USER_CURRENT_COURSE


class _UnavailableTabStorage:
    """Simulate NiceGUI tab storage before a client connection exists."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, int]] = []

    def get(self, _key: str) -> None:
        raise RuntimeError("app.storage.tab can only be used with a client connection")

    def __setitem__(self, key: str, value: int) -> None:
        self.writes.append((key, value))


@pytest.fixture()
def mock_storage():
    """Mock NiceGUI app.storage with tab and user dicts."""
    storage = MagicMock()
    storage.tab = {}
    storage.user = {}
    with patch("sophia.gui.state.course_state.app") as mock_app:
        mock_app.storage = storage
        yield storage


class TestGetCurrentCourse:
    def test_returns_tab_value_when_present(self, mock_storage: MagicMock) -> None:
        mock_storage.tab[TAB_CURRENT_COURSE] = 42
        mock_storage.user[USER_CURRENT_COURSE] = 99

        from sophia.gui.state.course_state import get_current_course

        assert get_current_course() == 42

    def test_falls_back_to_user_when_tab_empty(self, mock_storage: MagicMock) -> None:
        mock_storage.user[USER_CURRENT_COURSE] = 7

        from sophia.gui.state.course_state import get_current_course

        assert get_current_course() == 7

    def test_returns_none_when_both_empty(self, mock_storage: MagicMock) -> None:
        from sophia.gui.state.course_state import get_current_course

        assert get_current_course() is None

    def test_falls_back_to_user_when_tab_storage_unavailable(self, mock_storage: MagicMock) -> None:
        mock_storage.tab = _UnavailableTabStorage()
        mock_storage.user[USER_CURRENT_COURSE] = 11

        from sophia.gui.state.course_state import get_current_course

        assert get_current_course() == 11


class TestSetCurrentCourse:
    def test_writes_both_tiers(self, mock_storage: MagicMock) -> None:
        from sophia.gui.state.course_state import set_current_course

        set_current_course(5)

        assert mock_storage.tab[TAB_CURRENT_COURSE] == 5
        assert mock_storage.user[USER_CURRENT_COURSE] == 5


class TestInitCourseForTab:
    def test_copies_from_user_when_tab_empty(self, mock_storage: MagicMock) -> None:
        mock_storage.user[USER_CURRENT_COURSE] = 3

        from sophia.gui.state.course_state import init_course_for_tab

        init_course_for_tab()

        assert mock_storage.tab[TAB_CURRENT_COURSE] == 3

    def test_no_overwrite_when_tab_set(self, mock_storage: MagicMock) -> None:
        mock_storage.tab[TAB_CURRENT_COURSE] = 10
        mock_storage.user[USER_CURRENT_COURSE] = 20

        from sophia.gui.state.course_state import init_course_for_tab

        init_course_for_tab()

        assert mock_storage.tab[TAB_CURRENT_COURSE] == 10

    def test_noop_when_user_empty(self, mock_storage: MagicMock) -> None:
        from sophia.gui.state.course_state import init_course_for_tab

        init_course_for_tab()

        assert TAB_CURRENT_COURSE not in mock_storage.tab

    def test_noop_when_tab_storage_unavailable(self, mock_storage: MagicMock) -> None:
        mock_storage.tab = _UnavailableTabStorage()
        mock_storage.user[USER_CURRENT_COURSE] = 13

        from sophia.gui.state.course_state import init_course_for_tab

        init_course_for_tab()

        assert mock_storage.tab.writes == []
