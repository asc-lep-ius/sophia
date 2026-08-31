"""GUI-safe wrappers for Hermes lecture management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.gui.services.error_service import gui_error_handler
from sophia.infra.schema import lecture_downloads, lecture_modules
from sophia.services.hermes_manage import get_pipeline_status as _get_pipeline_status

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.infra.di import AppContainer
    from sophia.services.hermes_manage import EpisodeStatus

# --- Status filter constants -------------------------------------------------

STATUS_FILTER_ALL: Final = "all"
STATUS_FILTER_NEEDS_PROCESSING: Final = "needs_processing"
STATUS_FILTER_INDEXED: Final = "indexed"


# --- Data classes ------------------------------------------------------------


@dataclass
class ModuleInfo:
    """Minimal module reference for the lectures list."""

    module_id: int
    series_id: str
    course_name: str = ""


@dataclass
class DiscoveredModule:
    """A module discovered from Moodle/Opencast but not yet in the local DB."""

    course_shortname: str
    course_fullname: str
    module_id: int
    module_name: str
    episode_count: int


# --- Pure helpers (stateless, testable) --------------------------------------


def is_fully_indexed(ep: EpisodeStatus) -> bool:
    """True when downloaded, transcribed, AND indexed — all completed."""
    return (
        ep.download_status == "completed"
        and ep.transcription_status == "completed"
        and ep.index_status == "completed"
    )


def needs_processing(ep: EpisodeStatus) -> bool:
    """True when any pipeline step is not yet completed."""
    return not is_fully_indexed(ep)


def count_unprocessed(episodes: list[EpisodeStatus]) -> int:
    """Count episodes that still need pipeline processing."""
    return sum(1 for ep in episodes if needs_processing(ep))


def get_unprocessed(episodes: list[EpisodeStatus]) -> list[EpisodeStatus]:
    """Return only episodes that still need pipeline processing."""
    return [ep for ep in episodes if needs_processing(ep)]


def filter_episodes(
    episodes: list[EpisodeStatus],
    *,
    status_filter: str,
    search_query: str,
) -> list[EpisodeStatus]:
    """Apply status filter and title search to an episode list."""
    result = episodes

    if status_filter == STATUS_FILTER_INDEXED:
        result = [ep for ep in result if is_fully_indexed(ep)]
    elif status_filter == STATUS_FILTER_NEEDS_PROCESSING:
        result = [ep for ep in result if needs_processing(ep)]

    if search_query:
        query_lower = search_query.lower()
        result = [ep for ep in result if query_lower in ep.title.lower()]

    return result


# --- Async service wrappers --------------------------------------------------


@gui_error_handler(operation="get_lecture_modules", fallback=[])
async def get_lecture_modules(db: AsyncSession) -> list[ModuleInfo]:
    """Query distinct modules that have lecture downloads."""
    rows = (
        await db.execute(
            select(
                lecture_downloads.c.module_id,
                lecture_downloads.c.series_id,
                func.coalesce(lecture_modules.c.course_name, "").label("course_name"),
            )
            .select_from(lecture_downloads)
            .outerjoin(
                lecture_modules,
                lecture_downloads.c.module_id == lecture_modules.c.module_id,
            )
            .distinct()
        )
    ).all()
    return [
        ModuleInfo(
            module_id=row.module_id,
            series_id=row.series_id,
            course_name=row.course_name,
        )
        for row in rows
    ]


@gui_error_handler(operation="get_module_lectures", fallback=[])
async def get_module_lectures(db: AsyncSession, module_id: int) -> list[EpisodeStatus]:
    """Fetch pipeline status for all episodes in a module."""
    return await _get_pipeline_status(db, module_id)


# --- Discovery (Moodle + Opencast) ------------------------------------------


async def discover_lecture_modules(container: AppContainer) -> list[DiscoveredModule]:
    """Query Moodle for enrolled courses and find Opencast modules with episodes.

    Returns only modules that have at least one episode. Persists course→module
    mappings to the lecture_modules table for display name resolution.
    """
    courses = await container.moodle.get_enrolled_courses()
    if not courses:
        return []

    sections_by_course = await asyncio.gather(
        *(container.moodle.get_course_content(c.id) for c in courses),
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

    async with container.session() as db:
        for shortname, fullname, mid, _name in opencast_modules:
            statement = pg_insert(lecture_modules).values(
                module_id=mid,
                course_name=fullname,
                course_shortname=shortname,
            )
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[lecture_modules.c.module_id],
                    set_={
                        "course_name": statement.excluded.course_name,
                        "course_shortname": statement.excluded.course_shortname,
                    },
                )
            )

    episode_lists = await asyncio.gather(
        *(container.opencast.get_series_episodes(mid) for _, _, mid, _ in opencast_modules),
    )

    return [
        DiscoveredModule(
            course_shortname=shortname,
            course_fullname=fullname,
            module_id=mid,
            module_name=name,
            episode_count=len(episodes),
        )
        for (shortname, fullname, mid, name), episodes in zip(
            opencast_modules,
            episode_lists,
            strict=True,
        )
        if episodes
    ]
