"""GUI-safe wrappers for quickstart wizard data fetching."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from sophia.services.athena_confidence import rate_confidence as _rate_confidence
from sophia.services.athena_study import get_course_topics as _get_course_topics
from sophia.services.athena_study import save_manual_topic as _save_manual_topic
from sophia.services.chronos import get_deadlines as _get_deadlines

if TYPE_CHECKING:
    from sophia.domain.models import Course, Deadline, TopicMapping
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


async def get_enrolled_courses(app: AppContainer) -> list[Course]:
    """Fetch enrolled courses from Moodle, returning empty on error."""
    try:
        return await app.moodle.get_enrolled_courses()
    except Exception:
        log.exception("quickstart_get_courses_failed")
        return []


async def get_topics_for_courses(
    app: AppContainer,
    course_ids: list[int],
) -> list[TopicMapping]:
    """Fetch and flatten topics for multiple courses."""
    try:
        results: list[TopicMapping] = []
        for cid in course_ids:
            topics = await _get_course_topics(app, cid)
            results.extend(topics)
        return results
    except Exception:
        log.exception("quickstart_get_topics_failed", course_ids=course_ids)
        return []


async def get_nearest_deadline(app: AppContainer) -> Deadline | None:
    """Get the closest upcoming deadline, or None."""
    try:
        deadlines = await _get_deadlines(app.db, horizon_days=90)
        return deadlines[0] if deadlines else None
    except Exception:
        log.exception("quickstart_get_deadline_failed")
        return None


async def save_initial_confidence(
    app: AppContainer,
    *,
    course_id: int,
    ratings: dict[str, int],
) -> None:
    """Save first confidence ratings from the wizard."""
    try:
        for topic, score in ratings.items():
            await _rate_confidence(app, topic, course_id, score)
        log.info("quickstart_confidence_saved", count=len(ratings))
    except Exception:
        log.exception("quickstart_save_confidence_failed")


async def save_manual_topics(
    app: AppContainer,
    *,
    course_id: int,
    topics: list[str],
) -> list[TopicMapping]:
    """Save manual topics from the wizard. Returns saved TopicMappings."""
    try:
        saved: list[TopicMapping] = []
        for t in topics:
            mapping = await _save_manual_topic(app, t, course_id)
            if mapping is not None:
                saved.append(mapping)
        log.info("quickstart_manual_topics_saved", count=len(saved))
        return saved
    except Exception:
        log.exception("quickstart_save_manual_topics_failed")
        return []


async def get_completed_session_count(app: AppContainer) -> int:
    """Count total completed study sessions across all courses."""
    try:
        cursor = await app.db.execute("SELECT COUNT(*) FROM study_sessions")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        log.exception("quickstart_session_count_failed")
        return 0
