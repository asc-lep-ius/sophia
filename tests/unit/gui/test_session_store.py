"""Tests for SessionStore — save, load, pause, discard, list sessions."""

from __future__ import annotations

import pytest

from sophia.gui.state.session_store import SessionState, SessionStore


@pytest.fixture
def storage() -> dict[str, object]:
    """Fake app.storage.user as a plain dict."""
    return {}


@pytest.fixture
def store(storage: dict[str, object]) -> SessionStore:
    return SessionStore(storage)


class TestSessionState:
    def test_defaults(self) -> None:
        state = SessionState(topic="Limits", course_id=42, mode="practice")
        assert state.step_index == 0
        assert state.answers == {}
        assert state.pre_test_score is None
        assert state.post_test_score is None
        assert state.timer_elapsed == 0.0
        assert state.paused_at is None
        assert state.started_at is not None

    def test_to_dict_roundtrip(self) -> None:
        state = SessionState(
            topic="Integrals",
            course_id=7,
            mode="exam",
            step_index=3,
            answers={"q1": "yes"},
            timer_elapsed=42.5,
        )
        d = state.to_dict()
        restored = SessionState.from_dict(d)
        assert restored.topic == "Integrals"
        assert restored.step_index == 3
        assert restored.answers == {"q1": "yes"}
        assert restored.timer_elapsed == 42.5


class TestSaveAndLoad:
    def test_save_creates_active_sessions_key(
        self,
        store: SessionStore,
        storage: dict[str, object],
    ) -> None:
        state = SessionState(topic="Limits", course_id=1, mode="practice")
        store.save_state("sess-1", state)
        sessions = storage["active_sessions"]
        assert isinstance(sessions, dict)
        assert "sess-1" in sessions

    def test_load_returns_saved_state(self, store: SessionStore) -> None:
        state = SessionState(topic="Calc", course_id=2, mode="review", step_index=5)
        store.save_state("s1", state)
        loaded = store.load_state("s1")
        assert loaded is not None
        assert loaded.topic == "Calc"
        assert loaded.step_index == 5

    def test_load_returns_none_for_unknown_session(self, store: SessionStore) -> None:
        assert store.load_state("nonexistent") is None

    def test_save_overwrites_existing(self, store: SessionStore) -> None:
        s1 = SessionState(topic="A", course_id=1, mode="m")
        store.save_state("s1", s1)
        s2 = SessionState(topic="B", course_id=1, mode="m", step_index=10)
        store.save_state("s1", s2)
        loaded = store.load_state("s1")
        assert loaded is not None
        assert loaded.topic == "B"
        assert loaded.step_index == 10


class TestPauseSession:
    def test_pause_sets_paused_at(self, store: SessionStore) -> None:
        state = SessionState(topic="X", course_id=1, mode="m")
        store.save_state("s1", state)
        store.pause_session("s1")
        loaded = store.load_state("s1")
        assert loaded is not None
        assert loaded.paused_at is not None

    def test_pause_nonexistent_is_noop(self, store: SessionStore) -> None:
        store.pause_session("ghost")  # should not raise


class TestDiscardSession:
    def test_discard_removes_from_active(self, store: SessionStore) -> None:
        state = SessionState(topic="Y", course_id=1, mode="m")
        store.save_state("s1", state)
        store.discard_session("s1")
        assert store.load_state("s1") is None

    def test_discard_nonexistent_is_noop(self, store: SessionStore) -> None:
        store.discard_session("ghost")  # should not raise


class TestListActiveSessions:
    def test_list_empty(self, store: SessionStore) -> None:
        assert store.list_active_sessions() == {}

    def test_list_returns_all_saved(self, store: SessionStore) -> None:
        store.save_state("a", SessionState(topic="A", course_id=1, mode="m"))
        store.save_state("b", SessionState(topic="B", course_id=2, mode="m"))
        sessions = store.list_active_sessions()
        assert len(sessions) == 2
        assert "a" in sessions
        assert "b" in sessions
