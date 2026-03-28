"""NiceGUI storage tier → data-type mapping.

NiceGUI exposes five storage tiers (see https://nicegui.io/documentation/storage).
This module documents which application data should live in each tier so that
components and services can access the right storage without guessing.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Tier keys — use these constants when accessing ``app.storage.*``
# ---------------------------------------------------------------------------

# ``app.storage.general`` — server-wide singleton, lives in-process.
# Stores the AppContainer reference so any page handler can reach DI services.
GENERAL_APP_CONTAINER: Final = "app_container"

# ``app.storage.user`` — per-user, persisted as file-backed JSON.
USER_CURRENT_COURSE: Final = "current_course"
USER_ACTIVE_TOPIC: Final = "active_study_topic"
USER_PREFERENCES: Final = "preferences"
USER_ACTIVE_SESSIONS: Final = "active_sessions"
USER_HERMES_SETUP_COMPLETE: Final = "hermes_setup_complete"

# ``app.storage.tab`` — per browser tab, lost on tab close.
TAB_STEPPER_STATE: Final = "stepper_state"
TAB_IN_PROGRESS_ANSWERS: Final = "in_progress_answers"
TAB_TIMER_STATE: Final = "timer_state"
TAB_REVIEW_INDEX: Final = "review_current_index"
TAB_REVIEW_SCORES: Final = "review_session_scores"
TAB_REVIEW_SHOW_BACK: Final = "review_show_back"
TAB_REVIEW_RECALL_TEXT: Final = "review_recall_text"

# Tab-scoped — study session stepper
TAB_STUDY_STEP_INDEX: Final = "study_step_index"
TAB_STUDY_PRE_ANSWERS: Final = "study_pre_answers"
TAB_STUDY_PRE_CONFIDENCE: Final = "study_pre_confidence"
TAB_STUDY_POST_ANSWERS: Final = "study_post_answers"
TAB_STUDY_POST_CONFIDENCE: Final = "study_post_confidence"
TAB_STUDY_REFLECTION: Final = "study_reflection"
TAB_STUDY_INSIGHT: Final = "study_insight"
TAB_STUDY_TIMER_REMAINING: Final = "study_timer_remaining"
TAB_STUDY_INTERLEAVED: Final = "study_interleaved"
TAB_STUDY_TOPICS: Final = "study_topics"
TAB_STUDY_SESSION_ID: Final = "study_session_id"
TAB_STUDY_SESSION_IDS: Final = "study_session_ids"
TAB_STUDY_NOVEL_TOPIC: Final = "study_novel_topic"

# Tab-scoped — Hermes search
TAB_SEARCH_QUERY: Final = "search_query"
TAB_SEARCH_COURSE_FILTER: Final = "search_course_filter"
TAB_SEARCH_RESULTS: Final = "search_results"
TAB_SEARCH_SELECTED_INDEX: Final = "search_selected_index"
TAB_SEARCH_BLOOM_LEVEL: Final = "search_bloom_level"
TAB_SEARCH_BLOOM_RESPONSE: Final = "search_bloom_response"

# Tab-scoped — Lectures list
TAB_LECTURES_STATUS_FILTER: Final = "lectures_status_filter"
TAB_LECTURES_SEARCH_QUERY: Final = "lectures_search_query"

# Tab-scoped — Chronos deadlines
TAB_CHRONOS_COURSE_FILTER: Final = "chronos_course_filter"
TAB_CHRONOS_ACTIVE_TIMER: Final = "chronos_active_timer"
TAB_CHRONOS_ESTIMATE_DRAFT: Final = "chronos_estimate_draft"

# Tab-scoped — Calibration dashboard
TAB_CALIBRATION_COURSE_FILTER: Final = "calibration_course_filter"
TAB_CALIBRATION_CHART_TYPE: Final = "calibration_chart_type"

# Tab-scoped — Dashboard density
TAB_DENSITY_MODE: Final = "dashboard_density_mode"

# ``app.storage.client`` — per WebSocket connection, transient.
CLIENT_PANEL_STATE: Final = "panel_state"
CLIENT_SCROLL_POSITION: Final = "scroll_position"

# ``app.storage.browser`` — per browser (localStorage), survives restarts.
BROWSER_THEME_PREF: Final = "theme_pref"
BROWSER_LATEX_ASSIST_LEVEL: Final = "latex_assist_level"
BROWSER_HIGH_CONTRAST: Final = "high_contrast"
BROWSER_EFFORT_CAPACITY: Final = "effort_capacity"

# ---------------------------------------------------------------------------
# Tier summary — convenience mapping for documentation / introspection
# ---------------------------------------------------------------------------

TIER_MAP: Final[dict[str, list[str]]] = {
    "general": [GENERAL_APP_CONTAINER],
    "user": [
        USER_CURRENT_COURSE,
        USER_ACTIVE_TOPIC,
        USER_PREFERENCES,
        USER_ACTIVE_SESSIONS,
        USER_HERMES_SETUP_COMPLETE,
    ],
    "tab": [
        TAB_STEPPER_STATE,
        TAB_IN_PROGRESS_ANSWERS,
        TAB_TIMER_STATE,
        TAB_REVIEW_INDEX,
        TAB_REVIEW_SCORES,
        TAB_REVIEW_SHOW_BACK,
        TAB_REVIEW_RECALL_TEXT,
        TAB_STUDY_STEP_INDEX,
        TAB_STUDY_PRE_ANSWERS,
        TAB_STUDY_PRE_CONFIDENCE,
        TAB_STUDY_POST_ANSWERS,
        TAB_STUDY_POST_CONFIDENCE,
        TAB_STUDY_REFLECTION,
        TAB_STUDY_INSIGHT,
        TAB_STUDY_TIMER_REMAINING,
        TAB_STUDY_INTERLEAVED,
        TAB_STUDY_TOPICS,
        TAB_STUDY_SESSION_ID,
        TAB_STUDY_SESSION_IDS,
        TAB_STUDY_NOVEL_TOPIC,
        TAB_SEARCH_QUERY,
        TAB_SEARCH_COURSE_FILTER,
        TAB_SEARCH_RESULTS,
        TAB_SEARCH_SELECTED_INDEX,
        TAB_SEARCH_BLOOM_LEVEL,
        TAB_SEARCH_BLOOM_RESPONSE,
        TAB_LECTURES_STATUS_FILTER,
        TAB_LECTURES_SEARCH_QUERY,
        TAB_CHRONOS_COURSE_FILTER,
        TAB_CHRONOS_ACTIVE_TIMER,
        TAB_CHRONOS_ESTIMATE_DRAFT,
        TAB_CALIBRATION_COURSE_FILTER,
        TAB_CALIBRATION_CHART_TYPE,
        TAB_DENSITY_MODE,
    ],
    "client": [CLIENT_PANEL_STATE, CLIENT_SCROLL_POSITION],
    "browser": [
        BROWSER_THEME_PREF,
        BROWSER_LATEX_ASSIST_LEVEL,
        BROWSER_HIGH_CONTRAST,
        BROWSER_EFFORT_CAPACITY,
    ],
}
