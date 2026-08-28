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
            "/api/learning-paths/{learning_path_id}/topics",
            "/api/learning-paths/{learning_path_id}/topics/extract",
            "/api/learning-paths/{learning_path_id}/topics/confidence",
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
    "deadlines": frozenset(
        {
            "/api/deadlines",
            "/api/deadlines/sync",
            "/api/deadlines/estimates",
            "/api/deadlines/{deadline_id}/timer/start",
            "/api/deadlines/{deadline_id}/timer/stop",
            "/api/deadlines/{deadline_id}/tracked-time",
            "/api/deadlines/time-entries",
            "/api/deadlines/reflections",
            "/api/deadlines/{deadline_id}/complete",
            "/api/deadlines/workload",
            "/api/deadlines/upcoming-exams",
            "/api/deadlines/ics",
        }
    ),
    "deadline_history": frozenset(
        {
            "/api/deadline-history",
            "/api/deadline-history/{deadline_id}/reflection",
            "/api/deadline-history/{deadline_id}/time-entries",
            "/api/deadline-history/effort-distribution",
            "/api/deadline-history/calibration",
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
    "registration": frozenset(
        {
            "/api/integrations/tiss/registration/favorites",
            "/api/integrations/tiss/registration/attempts",
            "/api/integrations/tiss/registration/targets/{course_number}",
            "/api/integrations/tiss/registration/targets/{course_number}/groups",
            "/api/integrations/tiss/registration/targets/{course_number}/exam-dates",
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
