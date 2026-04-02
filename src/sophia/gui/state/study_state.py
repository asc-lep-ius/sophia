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
    return app.storage.tab.get(TAB_STUDY_STEP_INDEX, 0)


def set_step_index(idx: int) -> None:
    app.storage.tab[TAB_STUDY_STEP_INDEX] = idx


def get_pre_answers() -> dict[str, str]:
    return app.storage.tab.get(TAB_STUDY_PRE_ANSWERS, {})


def set_pre_answers(answers: dict[str, str]) -> None:
    app.storage.tab[TAB_STUDY_PRE_ANSWERS] = answers


def get_pre_confidence() -> dict[str, int]:
    return app.storage.tab.get(TAB_STUDY_PRE_CONFIDENCE, {})


def set_pre_confidence(conf: dict[str, int]) -> None:
    app.storage.tab[TAB_STUDY_PRE_CONFIDENCE] = conf


def get_post_answers() -> dict[str, str]:
    return app.storage.tab.get(TAB_STUDY_POST_ANSWERS, {})


def set_post_answers(answers: dict[str, str]) -> None:
    app.storage.tab[TAB_STUDY_POST_ANSWERS] = answers


def get_post_confidence() -> dict[str, int]:
    return app.storage.tab.get(TAB_STUDY_POST_CONFIDENCE, {})


def set_post_confidence(conf: dict[str, int]) -> None:
    app.storage.tab[TAB_STUDY_POST_CONFIDENCE] = conf


def get_reflection() -> str:
    return app.storage.tab.get(TAB_STUDY_REFLECTION, "")


def set_reflection(text: str) -> None:
    app.storage.tab[TAB_STUDY_REFLECTION] = text


def get_insight() -> str:
    return app.storage.tab.get(TAB_STUDY_INSIGHT, "")


def set_insight(text: str) -> None:
    app.storage.tab[TAB_STUDY_INSIGHT] = text


def get_timer_remaining() -> int:
    return app.storage.tab.get(TAB_STUDY_TIMER_REMAINING, DEFAULT_REFLECTION_SECONDS)


def set_timer_remaining(seconds: int) -> None:
    app.storage.tab[TAB_STUDY_TIMER_REMAINING] = seconds


def get_interleaved() -> bool:
    try:
        return app.storage.tab.get(TAB_STUDY_INTERLEAVED, False)
    except RuntimeError:
        return False


def set_interleaved(value: bool) -> None:
    app.storage.tab[TAB_STUDY_INTERLEAVED] = value


def get_topics() -> list[str]:
    return app.storage.tab.get(TAB_STUDY_TOPICS, [])


def set_topics(topics: list[str]) -> None:
    app.storage.tab[TAB_STUDY_TOPICS] = topics


def get_session_id() -> str:
    return app.storage.tab.get(TAB_STUDY_SESSION_ID, "")


def set_session_id(sid: str) -> None:
    app.storage.tab[TAB_STUDY_SESSION_ID] = sid


def get_session_ids() -> dict[str, int]:
    return app.storage.tab.get(TAB_STUDY_SESSION_IDS, {})


def set_session_ids(ids: dict[str, int]) -> None:
    app.storage.tab[TAB_STUDY_SESSION_IDS] = ids


def get_novel_topic() -> bool:
    return app.storage.tab.get(TAB_STUDY_NOVEL_TOPIC, False)


def set_novel_topic(value: bool) -> None:
    app.storage.tab[TAB_STUDY_NOVEL_TOPIC] = value


def get_course_id() -> int:
    return app.storage.user.get(USER_CURRENT_COURSE, 0)


def get_active_topic() -> str:
    return app.storage.user.get(USER_ACTIVE_TOPIC, "")


def reset_session_state() -> None:
    """Clear all tab-scoped study state for a fresh session."""
    app.storage.tab[TAB_STUDY_STEP_INDEX] = 0
    app.storage.tab[TAB_STUDY_PRE_ANSWERS] = {}
    app.storage.tab[TAB_STUDY_PRE_CONFIDENCE] = {}
    app.storage.tab[TAB_STUDY_POST_ANSWERS] = {}
    app.storage.tab[TAB_STUDY_POST_CONFIDENCE] = {}
    app.storage.tab[TAB_STUDY_REFLECTION] = ""
    app.storage.tab[TAB_STUDY_INSIGHT] = ""
    app.storage.tab[TAB_STUDY_TIMER_REMAINING] = DEFAULT_REFLECTION_SECONDS
    app.storage.tab[TAB_STUDY_SESSION_ID] = ""
    app.storage.tab[TAB_STUDY_NOVEL_TOPIC] = False
    app.storage.tab[TAB_STUDY_SESSION_IDS] = {}
