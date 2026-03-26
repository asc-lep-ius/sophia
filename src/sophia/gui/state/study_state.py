"""Study session tab-storage accessor functions.

Extracted from study.py to keep that module under the 800-line limit.
All functions here are thin wrappers around NiceGUI's tab/user storage.
"""

from __future__ import annotations

from typing import Final

from nicegui import app

from sophia.gui.state.storage_map import (
    TAB_STUDY_INSIGHT,
    TAB_STUDY_INTERLEAVED,
    TAB_STUDY_NOVEL_TOPIC,
    TAB_STUDY_POST_ANSWERS,
    TAB_STUDY_POST_CONFIDENCE,
    TAB_STUDY_PRE_ANSWERS,
    TAB_STUDY_PRE_CONFIDENCE,
    TAB_STUDY_REFLECTION,
    TAB_STUDY_SESSION_ID,
    TAB_STUDY_SESSION_IDS,
    TAB_STUDY_STEP_INDEX,
    TAB_STUDY_TIMER_REMAINING,
    TAB_STUDY_TOPICS,
    USER_ACTIVE_TOPIC,
    USER_CURRENT_COURSE,
)

DEFAULT_REFLECTION_SECONDS: Final = 30


def get_step_index() -> int:
    return app.storage.tab.get(TAB_STUDY_STEP_INDEX, 0)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_step_index(idx: int) -> None:
    app.storage.tab[TAB_STUDY_STEP_INDEX] = idx  # pyright: ignore[reportUnknownMemberType]


def get_pre_answers() -> dict[str, str]:
    return app.storage.tab.get(TAB_STUDY_PRE_ANSWERS, {})  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_pre_answers(answers: dict[str, str]) -> None:
    app.storage.tab[TAB_STUDY_PRE_ANSWERS] = answers  # pyright: ignore[reportUnknownMemberType]


def get_pre_confidence() -> dict[str, int]:
    return app.storage.tab.get(TAB_STUDY_PRE_CONFIDENCE, {})  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_pre_confidence(conf: dict[str, int]) -> None:
    app.storage.tab[TAB_STUDY_PRE_CONFIDENCE] = conf  # pyright: ignore[reportUnknownMemberType]


def get_post_answers() -> dict[str, str]:
    return app.storage.tab.get(TAB_STUDY_POST_ANSWERS, {})  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_post_answers(answers: dict[str, str]) -> None:
    app.storage.tab[TAB_STUDY_POST_ANSWERS] = answers  # pyright: ignore[reportUnknownMemberType]


def get_post_confidence() -> dict[str, int]:
    return app.storage.tab.get(TAB_STUDY_POST_CONFIDENCE, {})  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_post_confidence(conf: dict[str, int]) -> None:
    app.storage.tab[TAB_STUDY_POST_CONFIDENCE] = conf  # pyright: ignore[reportUnknownMemberType]


def get_reflection() -> str:
    return app.storage.tab.get(TAB_STUDY_REFLECTION, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_reflection(text: str) -> None:
    app.storage.tab[TAB_STUDY_REFLECTION] = text  # pyright: ignore[reportUnknownMemberType]


def get_insight() -> str:
    return app.storage.tab.get(TAB_STUDY_INSIGHT, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_insight(text: str) -> None:
    app.storage.tab[TAB_STUDY_INSIGHT] = text  # pyright: ignore[reportUnknownMemberType]


def get_timer_remaining() -> int:
    return app.storage.tab.get(TAB_STUDY_TIMER_REMAINING, DEFAULT_REFLECTION_SECONDS)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_timer_remaining(seconds: int) -> None:
    app.storage.tab[TAB_STUDY_TIMER_REMAINING] = seconds  # pyright: ignore[reportUnknownMemberType]


def get_interleaved() -> bool:
    try:
        return app.storage.tab.get(TAB_STUDY_INTERLEAVED, False)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]
    except RuntimeError:
        return False


def set_interleaved(value: bool) -> None:
    app.storage.tab[TAB_STUDY_INTERLEAVED] = value  # pyright: ignore[reportUnknownMemberType]


def get_topics() -> list[str]:
    return app.storage.tab.get(TAB_STUDY_TOPICS, [])  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_topics(topics: list[str]) -> None:
    app.storage.tab[TAB_STUDY_TOPICS] = topics  # pyright: ignore[reportUnknownMemberType]


def get_session_id() -> str:
    return app.storage.tab.get(TAB_STUDY_SESSION_ID, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_session_id(sid: str) -> None:
    app.storage.tab[TAB_STUDY_SESSION_ID] = sid  # pyright: ignore[reportUnknownMemberType]


def get_session_ids() -> dict[str, int]:
    return app.storage.tab.get(TAB_STUDY_SESSION_IDS, {})  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_session_ids(ids: dict[str, int]) -> None:
    app.storage.tab[TAB_STUDY_SESSION_IDS] = ids  # pyright: ignore[reportUnknownMemberType]


def get_novel_topic() -> bool:
    return app.storage.tab.get(TAB_STUDY_NOVEL_TOPIC, False)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def set_novel_topic(value: bool) -> None:
    app.storage.tab[TAB_STUDY_NOVEL_TOPIC] = value  # pyright: ignore[reportUnknownMemberType]


def get_course_id() -> int:
    return app.storage.user.get(USER_CURRENT_COURSE, 0)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def get_active_topic() -> str:
    return app.storage.user.get(USER_ACTIVE_TOPIC, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def reset_session_state() -> None:
    """Clear all tab-scoped study state for a fresh session."""
    app.storage.tab[TAB_STUDY_STEP_INDEX] = 0  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_PRE_ANSWERS] = {}  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_PRE_CONFIDENCE] = {}  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_POST_ANSWERS] = {}  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_POST_CONFIDENCE] = {}  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_REFLECTION] = ""  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_INSIGHT] = ""  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_TIMER_REMAINING] = DEFAULT_REFLECTION_SECONDS  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_SESSION_ID] = ""  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_NOVEL_TOPIC] = False  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_STUDY_SESSION_IDS] = {}  # pyright: ignore[reportUnknownMemberType]
