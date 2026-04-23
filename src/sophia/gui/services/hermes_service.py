"""GUI-safe wrappers for Hermes lecture management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sophia.gui.services.error_service import gui_error_handler
from sophia.services.hermes_manage import get_pipeline_status as _get_pipeline_status

if TYPE_CHECKING:
    import aiosqlite

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


@dataclass(frozen=True)
class EpisodeArtifacts:
    """Resolved artifact availability for a lecture episode."""

    episode_id: str
    module_id: int
    title: str
    download_status: str
    transcription_status: str | None
    index_status: str | None
    has_download: bool
    has_transcript: bool
    has_index: bool


@dataclass
class EpisodePipelineRecord:
    """Resolved pipeline metadata and artifact paths for a single episode."""

    episode_id: str
    module_id: int
    title: str
    download_status: str
    transcription_status: str | None
    index_status: str | None
    lecture_number: int | None
    download_path: str | None
    transcript_path: str | None


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
async def get_lecture_modules(db: aiosqlite.Connection) -> list[ModuleInfo]:
    """Query distinct modules that have lecture downloads."""
    cursor = await db.execute(
        "SELECT DISTINCT ld.module_id, ld.series_id, COALESCE(lm.course_name, '') "
        "FROM lecture_downloads ld "
        "LEFT JOIN lecture_modules lm ON ld.module_id = lm.module_id",
    )
    rows = await cursor.fetchall()
    return [ModuleInfo(module_id=row[0], series_id=row[1], course_name=row[2]) for row in rows]


@gui_error_handler(operation="get_module_lectures", fallback=[])
async def get_module_lectures(db: aiosqlite.Connection, module_id: int) -> list[EpisodeStatus]:
    """Fetch pipeline status for all episodes in a module."""
    return await _get_pipeline_status(db, module_id)


@gui_error_handler(operation="get_episode_artifacts", fallback={})
async def get_episode_artifacts(
    db: aiosqlite.Connection,
    episode_ids: list[str],
) -> dict[str, EpisodeArtifacts]:
    """Return resolved download/transcript/index artifact state for episodes."""
    if not episode_ids:
        return {}

    placeholders = ",".join("?" * len(episode_ids))
    cursor = await db.execute(
        f"""SELECT
               ld.episode_id,
               ld.module_id,
               ld.title,
               ld.status,
               ld.file_path,
               t.status,
               t.srt_path,
               ki.status
           FROM lecture_downloads ld
           LEFT JOIN transcriptions t ON t.episode_id = ld.episode_id
           LEFT JOIN knowledge_index ki ON ki.episode_id = ld.episode_id
           WHERE ld.episode_id IN ({placeholders})""",
        episode_ids,
    )
    rows = await cursor.fetchall()

    artifacts: dict[str, EpisodeArtifacts] = {}
    for row in rows:
        download_path = Path(row[4]) if row[4] else None
        transcript_path = Path(row[6]) if row[6] else None
        artifacts[row[0]] = EpisodeArtifacts(
            episode_id=row[0],
            module_id=row[1],
            title=row[2],
            download_status=row[3],
            transcription_status=row[5],
            index_status=row[7],
            has_download=(
                row[3] == "completed" and download_path is not None and download_path.exists()
            ),
            has_transcript=row[5] == "completed"
            and transcript_path is not None
            and transcript_path.exists(),
            has_index=row[7] == "completed",
        )

    return artifacts


async def get_episode_pipeline_records(
    db: aiosqlite.Connection,
    episode_ids: list[str],
) -> dict[str, EpisodePipelineRecord]:
    """Resolve module, status, and artifact paths for specific episodes."""
    if not episode_ids:
        return {}

    placeholders = ",".join("?" * len(episode_ids))
    cursor = await db.execute(
        f"""SELECT
               ld.episode_id,
               ld.module_id,
               ld.title,
               ld.status,
               t.status,
               ki.status,
               ld.lecture_number,
               ld.file_path,
               t.srt_path
           FROM lecture_downloads ld
           LEFT JOIN transcriptions t ON t.episode_id = ld.episode_id
           LEFT JOIN knowledge_index ki ON ki.episode_id = ld.episode_id
           WHERE ld.episode_id IN ({placeholders})""",  # noqa: S608
        episode_ids,
    )
    rows = await cursor.fetchall()
    return {
        row[0]: EpisodePipelineRecord(
            episode_id=row[0],
            module_id=row[1],
            title=row[2],
            download_status=row[3],
            transcription_status=row[4],
            index_status=row[5],
            lecture_number=row[6],
            download_path=row[7],
            transcript_path=row[8],
        )
        for row in rows
    }


async def has_download_artifact(db: aiosqlite.Connection, episode_id: str) -> bool:
    """Return True when the completed download points to a file on disk."""
    cursor = await db.execute(
        "SELECT file_path FROM lecture_downloads WHERE episode_id = ? AND status = 'completed'",
        (episode_id,),
    )
    row = await cursor.fetchone()
    return bool(row and row[0] and Path(row[0]).exists())


async def has_transcript_artifact(db: aiosqlite.Connection, episode_id: str) -> bool:
    """Return True when the completed transcription points to an SRT file on disk."""
    cursor = await db.execute(
        "SELECT srt_path FROM transcriptions WHERE episode_id = ? AND status = 'completed'",
        (episode_id,),
    )
    row = await cursor.fetchone()
    return bool(row and row[0] and Path(row[0]).exists())


async def has_index_artifact(db: aiosqlite.Connection, episode_id: str) -> bool:
    """Return True when an episode already has a completed index row."""
    cursor = await db.execute(
        "SELECT 1 FROM knowledge_index WHERE episode_id = ? AND status = 'completed'",
        (episode_id,),
    )
    return await cursor.fetchone() is not None


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

    for shortname, fullname, mid, _name in opencast_modules:
        await container.db.execute(
            "INSERT OR REPLACE INTO lecture_modules (module_id, course_name, course_shortname) "
            "VALUES (?, ?, ?)",
            (mid, fullname, shortname),
        )
    await container.db.commit()

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
