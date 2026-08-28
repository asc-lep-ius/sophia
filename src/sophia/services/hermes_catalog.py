"""Hermes lecture catalog read and discovery services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

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


async def get_lecture_modules(db: aiosqlite.Connection) -> list[LectureModule]:
    """Query distinct modules that have local lecture download records."""
    cursor = await db.execute(
        "SELECT DISTINCT ld.module_id, ld.series_id, COALESCE(lm.course_name, '') "
        "FROM lecture_downloads ld "
        "LEFT JOIN lecture_modules lm ON ld.module_id = lm.module_id "
        "ORDER BY COALESCE(lm.course_name, ''), ld.module_id",
    )
    rows = await cursor.fetchall()
    return [LectureModule(module_id=row[0], series_id=row[1], course_name=row[2]) for row in rows]


async def discover_lecture_modules(container: AppContainer) -> list[DiscoveredLectureModule]:
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
        await container.db.execute(
            "INSERT OR REPLACE INTO lecture_modules "
            "(module_id, course_name, course_shortname) VALUES (?, ?, ?)",
            (module_id, fullname, shortname),
        )
    await container.db.commit()

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
