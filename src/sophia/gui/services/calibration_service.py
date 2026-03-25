"""GUI-safe wrappers for calibration and confidence data fetching."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from sophia.services.athena_chronos import get_course_confidence as _get_course_confidence
from sophia.services.athena_confidence import (
    get_blind_spots as _get_blind_spots,
)
from sophia.services.athena_confidence import (
    get_confidence_ratings as _get_confidence_ratings,
)
from sophia.services.athena_session import get_study_sessions as _get_study_sessions

if TYPE_CHECKING:
    from sophia.domain.models import ConfidenceRating, StudySession
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Tier thresholds for mapping post-test scores to difficulty tiers
# ---------------------------------------------------------------------------
_TIER_EXPLAIN = 0.5
_TIER_TRANSFER = 0.8


# ---------------------------------------------------------------------------
# Async service wrappers
# ---------------------------------------------------------------------------


async def get_calibration_ratings(app: AppContainer, course_id: int) -> list[ConfidenceRating]:
    """Fetch confidence ratings for a course."""
    try:
        return await _get_confidence_ratings(app.db, course_id)
    except Exception:
        log.exception("get_calibration_ratings_failed", course_id=course_id)
        return []


async def get_blind_spot_topics(app: AppContainer, course_id: int) -> list[ConfidenceRating]:
    """Fetch overconfident blind-spot topics for a course."""
    try:
        return await _get_blind_spots(app.db, course_id)
    except Exception:
        log.exception("get_blind_spots_failed", course_id=course_id)
        return []


async def get_course_avg_confidence(app: AppContainer, course_id: int) -> float | None:
    """Get average confidence score for a course."""
    try:
        return await _get_course_confidence(app.db, course_id)
    except Exception:
        log.exception("get_course_confidence_failed", course_id=course_id)
        return None


async def get_study_sessions_for_topic(
    app: AppContainer, course_id: int, topic: str
) -> list[StudySession]:
    """Fetch study sessions for a specific topic."""
    try:
        return await _get_study_sessions(app.db, course_id, topic)
    except Exception:
        log.exception("get_study_sessions_failed", course_id=course_id, topic=topic)
        return []


# ---------------------------------------------------------------------------
# Pure chart data builders (no DB, no async)
# ---------------------------------------------------------------------------


def _score_to_tier(score: float | None) -> str:
    """Map a post-test score to a difficulty tier name."""
    if score is None or score < _TIER_EXPLAIN:
        return "cued"
    if score < _TIER_TRANSFER:
        return "explain"
    return "transfer"


def compute_tier_progression(sessions: list[StudySession]) -> list[dict[str, Any]]:
    """Map sessions to difficulty-tier progression over time.

    Returns list of ``{"session": index, "tier": "cued"|"explain"|"transfer", "score": value}``.
    """
    return [
        {
            "session": i,
            "tier": _score_to_tier(s.post_test_score),
            "score": s.post_test_score if s.post_test_score is not None else 0.0,
        }
        for i, s in enumerate(sessions)
    ]


def build_confidence_scatter_data(
    ratings: list[ConfidenceRating],
) -> dict[str, Any]:
    """Build ECharts scatter config for predicted vs actual confidence."""
    data = [[r.predicted, r.actual, r.topic] for r in ratings if r.actual is not None]
    return {
        "xAxis": {"name": "Predicted", "min": 0, "max": 1},
        "yAxis": {"name": "Actual", "min": 0, "max": 1},
        "series": [{"type": "scatter", "data": data}],
    }


def build_blind_spot_chart_data(
    ratings: list[ConfidenceRating],
) -> dict[str, Any]:
    """Build ECharts horizontal bar config for overconfident topics."""
    topics = [r.topic for r in ratings]
    gaps = [round(r.predicted - (r.actual or 0.0), 2) for r in ratings]
    return {
        "yAxis": {"type": "category", "data": topics},
        "xAxis": {"type": "value", "name": "Overconfidence gap"},
        "series": [{"type": "bar", "data": gaps}],
    }


def build_mastery_heatmap_data(
    ratings: list[ConfidenceRating],
) -> dict[str, Any]:
    """Build ECharts heatmap config for courses x topics."""
    topics = sorted({r.topic for r in ratings})
    course_ids = sorted({r.course_id for r in ratings})

    topic_idx = {t: i for i, t in enumerate(topics)}
    course_idx = {c: i for i, c in enumerate(course_ids)}

    data = [
        [topic_idx[r.topic], course_idx[r.course_id], r.actual if r.actual is not None else 0.0]
        for r in ratings
    ]
    return {
        "xAxis": {"type": "category", "data": topics},
        "yAxis": {"type": "category", "data": [str(c) for c in course_ids]},
        "visualMap": {"min": 0, "max": 1},
        "series": [{"type": "heatmap", "data": data}],
    }
