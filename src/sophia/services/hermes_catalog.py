"""Hermes lecture catalog read and discovery services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.infra.schema import lecture_downloads, lecture_modules

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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

    opencast_modules: list[tuple[str, str, int, str]] = []
    for course, sections in zip(courses, sections_by_course, strict=True):
        for section in sections:
            for module in section.modules:
                if module.modname == "opencast":
                    opencast_modules.append(
                        (course.shortname, course.fullname, module.id, module.name),
                    )

    if not opencast_modules:
        return []

    for shortname, fullname, module_id, _module_name in opencast_modules:
        statement = pg_insert(lecture_modules).values(
            module_id=module_id,
            course_name=fullname,
            course_shortname=shortname,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[lecture_modules.c.module_id],
                set_={
                    "course_name": statement.excluded.course_name,
                    "course_shortname": statement.excluded.course_shortname,
                },
            )
        )

    episode_lists = await asyncio.gather(
        *(
            container.opencast.get_series_episodes(module_id)
            for _, _, module_id, _ in opencast_modules
        ),
    )

    return [
        DiscoveredLectureModule(
            course_shortname=shortname,
            course_fullname=fullname,
            module_id=module_id,
            module_name=module_name,
            episode_count=len(episodes),
        )
        for (shortname, fullname, module_id, module_name), episodes in zip(
            opencast_modules,
            episode_lists,
            strict=True,
        )
        if episodes
    ]
