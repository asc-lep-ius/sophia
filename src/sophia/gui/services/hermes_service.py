"""GUI-safe wrappers for Hermes lecture management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from sophia.services.hermes_manage import get_pipeline_status as _get_pipeline_status

if TYPE_CHECKING:
    import aiosqlite

    from sophia.services.hermes_manage import EpisodeStatus

log = structlog.get_logger()

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


async def get_lecture_modules(db: aiosqlite.Connection) -> list[ModuleInfo]:
    """Query distinct modules that have lecture downloads."""
    try:
        cursor = await db.execute(
            "SELECT DISTINCT module_id, series_id FROM lecture_downloads",
        )
        rows = await cursor.fetchall()
        return [ModuleInfo(module_id=row[0], series_id=row[1]) for row in rows]
    except Exception:
        log.exception("get_lecture_modules_failed")
        return []


async def get_module_lectures(db: aiosqlite.Connection, module_id: int) -> list[EpisodeStatus]:
    """Fetch pipeline status for all episodes in a module."""
    try:
        return await _get_pipeline_status(db, module_id)
    except Exception:
        log.exception("get_module_lectures_failed", module_id=module_id)
        return []
