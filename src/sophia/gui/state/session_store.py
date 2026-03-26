"""Session store — save / load / pause / discard study-session state.

Session data is serialized into ``app.storage.user['active_sessions']`` as a
``dict[str, dict]`` keyed by *session_id*.  The caller is responsible for
scheduling auto-save (e.g. every 10 s); this module only provides the
save / load primitives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sophia.gui.state.storage_map import USER_ACTIVE_SESSIONS


@dataclass
class SessionState:
    """Snapshot of an in-progress study session."""

    topic: str
    course_id: int
    mode: str

    step_index: int = 0
    answers: dict[str, str] = field(default_factory=lambda: {})
    pre_test_score: float | None = None
    post_test_score: float | None = None
    timer_elapsed: float = 0.0
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    paused_at: str | None = None

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "course_id": self.course_id,
            "mode": self.mode,
            "step_index": self.step_index,
            "answers": self.answers,
            "pre_test_score": self.pre_test_score,
            "post_test_score": self.post_test_score,
            "timer_elapsed": self.timer_elapsed,
            "started_at": self.started_at,
            "paused_at": self.paused_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        return cls(
            topic=data["topic"],
            course_id=data["course_id"],
            mode=data["mode"],
            step_index=data.get("step_index", 0),
            answers=data.get("answers", {}),
            pre_test_score=data.get("pre_test_score"),
            post_test_score=data.get("post_test_score"),
            timer_elapsed=data.get("timer_elapsed", 0.0),
            started_at=data.get("started_at", datetime.now(UTC).isoformat()),
            paused_at=data.get("paused_at"),
        )


class SessionStore:
    """Read/write session state against a dict-like storage backend.

    *storage* should be ``app.storage.user`` (or a plain ``dict`` in tests).
    """

    def __init__(self, storage: dict[str, Any]) -> None:
        self._storage = storage

    # -- helpers -------------------------------------------------------------

    def _sessions(self) -> dict[str, dict[str, Any]]:
        return self._storage.setdefault(USER_ACTIVE_SESSIONS, {})

    # -- public API ----------------------------------------------------------

    def save_state(self, session_id: str, state: SessionState) -> None:
        self._sessions()[session_id] = state.to_dict()

    def load_state(self, session_id: str) -> SessionState | None:
        data = self._sessions().get(session_id)
        if data is None:
            return None
        return SessionState.from_dict(data)

    def pause_session(self, session_id: str) -> None:
        data = self._sessions().get(session_id)
        if data is None:
            return
        data["paused_at"] = datetime.now(UTC).isoformat()

    def discard_session(self, session_id: str) -> None:
        self._sessions().pop(session_id, None)

    def list_active_sessions(self) -> dict[str, SessionState]:
        return {sid: SessionState.from_dict(d) for sid, d in self._sessions().items()}
