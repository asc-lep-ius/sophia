"""Hermes lecture catalog read and discovery services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.infra.schema import DEFAULT_SCOPE, lecture_downloads, lecture_modules

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.domain.models import Course
    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class LectureModule:
    """Minimal module reference for lecture catalog surfaces."""

    module_id: int
    series_id: str
    course_name: str = ""


@dataclass(frozen=True, slots=True)
class DiscoveredLectureModule:
    """Lecture module discovered from Moodle and Opencast."""

    course_shortname: str
    course_fullname: str
    module_id: int
    module_name: str
    episode_count: int


async def get_lecture_modules(session: AsyncSession) -> list[LectureModule]:
    """Query distinct modules that have local lecture download records."""
    course_name = func.coalesce(lecture_modules.c.course_name, "")
    rows = (
        await session.execute(
            select(
                lecture_downloads.c.module_id,
                lecture_downloads.c.series_id,
                course_name.label("course_name"),
            )
            .select_from(lecture_downloads)
            .outerjoin(
                lecture_modules,
                lecture_downloads.c.module_id == lecture_modules.c.module_id,
            )
            .distinct()
            .order_by(course_name, lecture_downloads.c.module_id)
        )
    ).all()
    return [
        LectureModule(
            module_id=row.module_id,
            series_id=row.series_id,
            course_name=row.course_name,
        )
        for row in rows
    ]


async def get_lecture_module_course_id(session: AsyncSession, module_id: int) -> str | None:
    """Return the course a lecture module belongs to, as persisted at discovery.

    ``None`` means the owner is unknown — either the module has no metadata row
    at all, or its row predates course scoping and still carries
    :data:`DEFAULT_SCOPE`. Callers deciding access must treat both as unowned
    rather than as a wildcard; rediscovery repopulates the scope.
    """
    course_id = await session.scalar(
        select(lecture_modules.c.course_id).where(lecture_modules.c.module_id == module_id),
    )
    if course_id is None or str(course_id) == DEFAULT_SCOPE:
        return None
    return str(course_id)


async def discover_lecture_modules(
    container: AppContainer,
    session: AsyncSession,
) -> list[DiscoveredLectureModule]:
    """Find Opencast lecture modules from enrolled Moodle courses and persist mappings."""
    courses = await container.moodle.get_enrolled_courses()
    if not courses:
        return []

    sections_by_course = await asyncio.gather(
        *(container.moodle.get_course_content(course.id) for course in courses),
    )

    opencast_modules: list[tuple[Course, int, str]] = []
    for course, sections in zip(courses, sections_by_course, strict=True):
        for section in sections:
            for module in section.modules:
                if module.modname == "opencast":
                    opencast_modules.append((course, module.id, module.name))

    if not opencast_modules:
        return []

    # course_id is what proves a module's owner to the search scope check; a row
    # left at DEFAULT_SCOPE reads as unowned, so discovery has to write it.
    for course, module_id, _module_name in opencast_modules:
        statement = pg_insert(lecture_modules).values(
            module_id=module_id,
            course_name=course.fullname,
            course_shortname=course.shortname,
            course_id=str(course.id),
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[lecture_modules.c.module_id],
                set_={
                    "course_name": statement.excluded.course_name,
                    "course_shortname": statement.excluded.course_shortname,
                    "course_id": statement.excluded.course_id,
                },
            )
        )

    episode_lists = await asyncio.gather(
        *(
            container.opencast.get_series_episodes(module_id)
            for _, module_id, _ in opencast_modules
        ),
    )

    return [
        DiscoveredLectureModule(
            course_shortname=course.shortname,
            course_fullname=course.fullname,
            module_id=module_id,
            module_name=module_name,
            episode_count=len(episodes),
        )
        for (course, module_id, module_name), episodes in zip(
            opencast_modules,
            episode_lists,
            strict=True,
        )
        if episodes
    ]
