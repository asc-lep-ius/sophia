"""API-safe quickstart aggregation and persistence operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from sophia.domain.models import Course, Deadline, TopicMapping  # noqa: TC001
from sophia.infra.schema import study_sessions
from sophia.services.athena_confidence import rate_confidence
from sophia.services.athena_study import get_course_topics, save_manual_topic
from sophia.services.chronos import get_deadlines
from sophia.services.content_language import sync_learning_path_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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
    session: AsyncSession,
    *,
    course_id: int | None = None,
) -> QuickstartOverview:
    """Aggregate the quickstart wizard's course, topic, deadline, and session data."""
    courses = await get_enrolled_courses(app)
    await sync_learning_path_settings(session, courses)
    visible_courses = [course for course in courses if course_id is None or course.id == course_id]
    topic_course_ids = [course_id] if course_id is not None else [course.id for course in courses]
    topics = await get_topics_for_courses(session, topic_course_ids)
    nearest_deadline = await get_nearest_deadline(session, course_id=course_id)
    completed_session_count = await get_completed_session_count(session, course_id=course_id)
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
    session: AsyncSession,
    course_ids: list[int],
) -> list[TopicMapping]:
    """Fetch persisted topics for multiple courses."""
    topics: list[TopicMapping] = []
    for course_id in course_ids:
        topics.extend(await get_course_topics(session, course_id))
    return topics


async def get_nearest_deadline(
    session: AsyncSession,
    *,
    course_id: int | None = None,
) -> Deadline | None:
    """Get the closest upcoming deadline for the selected quickstart course."""
    deadlines = await get_deadlines(session, course_id=course_id, horizon_days=90)
    return deadlines[0] if deadlines else None


async def save_initial_confidence(
    session: AsyncSession,
    *,
    course_id: int,
    ratings: dict[str, int],
) -> int:
    """Save initial confidence ratings and return how many were persisted."""
    for topic, score in ratings.items():
        await rate_confidence(session, topic, course_id, score)
    return len(ratings)


async def save_manual_topics(
    session: AsyncSession,
    *,
    course_id: int,
    topics: list[str],
) -> list[TopicMapping]:
    """Save manual quickstart topics and return the newly persisted mappings."""
    saved: list[TopicMapping] = []
    for topic in topics:
        mapping = await save_manual_topic(session, topic, course_id)
        if mapping is not None:
            saved.append(mapping)
    return saved


async def get_completed_session_count(
    session: AsyncSession,
    *,
    course_id: int | None = None,
) -> int:
    """Count completed study sessions, optionally scoped to one course."""
    query = (
        select(func.count())
        .select_from(study_sessions)
        .where(study_sessions.c.completed_at.is_not(None))
    )
    if course_id is not None:
        query = query.where(study_sessions.c.course_id == course_id)
    return await session.scalar(query) or 0
