"""GUI-safe wrappers for TISS registration actions.

The behaviour lives in :mod:`sophia.services.tiss_registration` so the HTTP API
can reach it without importing the GUI package; this module keeps the import
path the NiceGUI pages already use.
"""

from __future__ import annotations

from sophia.services.tiss_registration import (
    FavoritesResult,
    GroupsResult,
    RegisterResult,
    StatusResult,
    current_semester,
    get_exam_dates,
    get_favorites,
    get_groups,
    get_registration_status,
    register_course,
)

__all__ = [
    "FavoritesResult",
    "GroupsResult",
    "RegisterResult",
    "StatusResult",
    "current_semester",
    "get_exam_dates",
    "get_favorites",
    "get_groups",
    "get_registration_status",
    "register_course",
]
