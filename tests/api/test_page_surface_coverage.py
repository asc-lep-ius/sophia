"""OpenAPI surface coverage for issue #94 page/domain families."""

from __future__ import annotations

from ._session_helpers import build_harness

EXPECTED_SURFACE_PATHS: dict[str, frozenset[str]] = {
    "content_sources": frozenset(
        {
            "/api/content-sources",
            "/api/content-sources/discover",
            "/api/content-sources/{content_source_id}/content-items",
            "/api/content-sources/{content_source_id}/ingestion-status",
        }
    ),
    "topics": frozenset(
        {
            "/api/topics",
            "/api/topics/extract",
            "/api/topics/manual",
            "/api/topics/confidence",
        }
    ),
    "study": frozenset(
        {
            "/api/study/sessions",
            "/api/study/sessions/{session_id}/complete",
            "/api/study/flashcards",
        }
    ),
    "review": frozenset(
        {
            "/api/review/due",
            "/api/review/upcoming",
            "/api/review/schedules",
            "/api/review/complete",
        }
    ),
    "chronos": frozenset(
        {
            "/api/chronos/deadlines",
            "/api/chronos/sync",
            "/api/chronos/estimates",
            "/api/chronos/timers/{deadline_id}/start",
            "/api/chronos/timers/{deadline_id}/stop",
            "/api/chronos/deadlines/{deadline_id}/tracked-time",
            "/api/chronos/time-entries",
            "/api/chronos/reflections",
            "/api/chronos/deadlines/{deadline_id}/complete",
            "/api/chronos/workload",
            "/api/chronos/upcoming-exams",
            "/api/chronos/ics",
        }
    ),
    "chronos_history": frozenset(
        {
            "/api/chronos-history/deadlines",
            "/api/chronos-history/deadlines/{deadline_id}/reflection",
            "/api/chronos-history/deadlines/{deadline_id}/time-entries",
            "/api/chronos-history/effort-distribution",
            "/api/chronos-history/calibration",
        }
    ),
    "search": frozenset({"/api/search"}),
    "calibration": frozenset(
        {
            "/api/calibration/ratings",
            "/api/calibration/blind-spots",
            "/api/calibration/actual-score",
        }
    ),
    "quickstart": frozenset(
        {
            "/api/quickstart/overview",
            "/api/quickstart/confidence",
            "/api/quickstart/manual-topics",
            "/api/quickstart/session-count",
        }
    ),
}


def test_issue_94_page_surfaces_are_visible_in_openapi() -> None:
    openapi_paths = frozenset(build_harness().app.openapi()["paths"])

    missing_paths_by_surface = {
        surface: sorted(expected_paths - openapi_paths)
        for surface, expected_paths in EXPECTED_SURFACE_PATHS.items()
        if not expected_paths.issubset(openapi_paths)
    }

    assert missing_paths_by_surface == {}
