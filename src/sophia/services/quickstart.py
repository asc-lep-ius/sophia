"""API-safe quickstart aggregation and persistence operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sophia.domain.models import Course, Deadline, TopicMapping  # noqa: TC001
from sophia.services.athena_confidence import rate_confidence
from sophia.services.athena_study import get_course_topics, save_manual_topic
from sophia.services.chronos import get_deadlines
from sophia.services.content_language import sync_learning_path_settings

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

DbRow = tuple[object, ...]


@dataclass(frozen=True, slots=True)
class QuickstartOverview:
    courses: list[Course]
    topics: list[TopicMapping]
    nearest_deadline: Deadline | None
    completed_session_count: int


async def get_quickstart_overview(
    app: AppContainer,
    *,
    course_id: int | None = None,
) -> QuickstartOverview:
    """Aggregate the quickstart wizard's course, topic, deadline, and session data."""
    courses = await get_enrolled_courses(app)
    await sync_learning_path_settings(app.db, courses)
    visible_courses = [course for course in courses if course_id is None or course.id == course_id]
    topic_course_ids = [course_id] if course_id is not None else [course.id for course in courses]
    topics = await get_topics_for_courses(app, topic_course_ids)
    nearest_deadline = await get_nearest_deadline(app, course_id=course_id)
    completed_session_count = await get_completed_session_count(app, course_id=course_id)
    return QuickstartOverview(
        courses=visible_courses,
        topics=topics,
        nearest_deadline=nearest_deadline,
        completed_session_count=completed_session_count,
    )


async def get_enrolled_courses(app: AppContainer) -> list[Course]:
    """Fetch enrolled courses from Moodle without GUI fallback swallowing."""
    return await app.moodle.get_enrolled_courses()


async def get_topics_for_courses(
    app: AppContainer,
    course_ids: list[int],
) -> list[TopicMapping]:
    """Fetch persisted topics for multiple courses."""
    topics: list[TopicMapping] = []
    for course_id in course_ids:
        topics.extend(await get_course_topics(app, course_id))
    return topics


async def get_nearest_deadline(
    app: AppContainer,
    *,
    course_id: int | None = None,
) -> Deadline | None:
    """Get the closest upcoming deadline for the selected quickstart course."""
    deadlines = await get_deadlines(app.db, course_id=course_id, horizon_days=90)
    return deadlines[0] if deadlines else None


async def save_initial_confidence(
    app: AppContainer,
    *,
    course_id: int,
    ratings: dict[str, int],
) -> int:
    """Save initial confidence ratings and return how many were persisted."""
    for topic, score in ratings.items():
        await rate_confidence(app, topic, course_id, score)
    return len(ratings)


async def save_manual_topics(
    app: AppContainer,
    *,
    course_id: int,
    topics: list[str],
) -> list[TopicMapping]:
    """Save manual quickstart topics and return the newly persisted mappings."""
    saved: list[TopicMapping] = []
    for topic in topics:
        mapping = await save_manual_topic(app, topic, course_id)
        if mapping is not None:
            saved.append(mapping)
    return saved


async def get_completed_session_count(
    app: AppContainer,
    *,
    course_id: int | None = None,
) -> int:
    """Count completed study sessions, optionally scoped to one course."""
    query = "SELECT COUNT(*) FROM study_sessions WHERE completed_at IS NOT NULL"
    params: tuple[int, ...] = ()
    if course_id is not None:
        query += " AND course_id = ?"
        params = (course_id,)

    cursor = await app.db.execute(query, params)
    row = cast("DbRow | None", await cursor.fetchone())
    return _int_cell(row[0]) if row is not None else 0


def _int_cell(value: object) -> int:
    if isinstance(value, int | float | str):
        return int(value)
    msg = "database value must be convertible to int"
    raise TypeError(msg)
