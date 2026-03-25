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

# ``app.storage.tab`` — per browser tab, lost on tab close.
TAB_STEPPER_STATE: Final = "stepper_state"
TAB_IN_PROGRESS_ANSWERS: Final = "in_progress_answers"
TAB_TIMER_STATE: Final = "timer_state"
TAB_REVIEW_INDEX: Final = "review_current_index"
TAB_REVIEW_SCORES: Final = "review_session_scores"
TAB_REVIEW_SHOW_BACK: Final = "review_show_back"
TAB_REVIEW_RECALL_TEXT: Final = "review_recall_text"

# ``app.storage.client`` — per WebSocket connection, transient.
CLIENT_PANEL_STATE: Final = "panel_state"
CLIENT_SCROLL_POSITION: Final = "scroll_position"

# ``app.storage.browser`` — per browser (localStorage), survives restarts.
BROWSER_DENSITY_MODE: Final = "dashboard_density_mode"
BROWSER_THEME_PREF: Final = "theme_pref"
BROWSER_LATEX_ASSIST_LEVEL: Final = "latex_assist_level"

# ---------------------------------------------------------------------------
# Tier summary — convenience mapping for documentation / introspection
# ---------------------------------------------------------------------------

TIER_MAP: Final[dict[str, list[str]]] = {
    "general": [GENERAL_APP_CONTAINER],
    "user": [USER_CURRENT_COURSE, USER_ACTIVE_TOPIC, USER_PREFERENCES, USER_ACTIVE_SESSIONS],
    "tab": [
        TAB_STEPPER_STATE, TAB_IN_PROGRESS_ANSWERS, TAB_TIMER_STATE,
        TAB_REVIEW_INDEX, TAB_REVIEW_SCORES, TAB_REVIEW_SHOW_BACK, TAB_REVIEW_RECALL_TEXT,
    ],
    "client": [CLIENT_PANEL_STATE, CLIENT_SCROLL_POSITION],
    "browser": [BROWSER_DENSITY_MODE, BROWSER_THEME_PREF, BROWSER_LATEX_ASSIST_LEVEL],
}
