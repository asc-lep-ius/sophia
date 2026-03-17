"""Hermes lecture management — discard, restore, pipeline status."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import aiosqlite

log = structlog.get_logger()


@dataclass
class EpisodeStatus:
    episode_id: str
    title: str
    download_status: str
    skip_reason: str | None
    transcription_status: str | None
    index_status: str | None


async def discard_episode(
    db: aiosqlite.Connection, module_id: int, episode_id: str
) -> bool:
    """Mark an episode as discarded. Returns True if updated, False if not found."""
    cursor = await db.execute(
        """UPDATE lecture_downloads SET status = 'discarded'
           WHERE episode_id = ? AND module_id = ?
             AND status IN ('completed', 'skipped', 'failed')""",
        (episode_id, module_id),
    )
    await db.commit()
    updated = cursor.rowcount > 0
    if updated:
        log.info("episode_discarded", episode_id=episode_id, module_id=module_id)
    return updated


async def restore_episode(
    db: aiosqlite.Connection, module_id: int, episode_id: str
) -> bool:
    """Restore a discarded episode back to queued. Returns True if restored."""
    cursor = await db.execute(
        """UPDATE lecture_downloads SET status = 'queued'
           WHERE episode_id = ? AND module_id = ? AND status = 'discarded'""",
        (episode_id, module_id),
    )
    await db.commit()
    restored = cursor.rowcount > 0
    if restored:
        log.info("episode_restored", episode_id=episode_id, module_id=module_id)
    return restored


async def get_pipeline_status(
    db: aiosqlite.Connection, module_id: int
) -> list[EpisodeStatus]:
    """Query per-episode pipeline state for a module."""
    cursor = await db.execute(
        """SELECT
               ld.episode_id,
               ld.title,
               ld.status,
               ld.skip_reason,
               t.status,
               ki.status
           FROM lecture_downloads ld
           LEFT JOIN transcriptions t ON t.episode_id = ld.episode_id
           LEFT JOIN knowledge_index ki ON ki.episode_id = ld.episode_id
           WHERE ld.module_id = ?
           ORDER BY ld.title""",
        (module_id,),
    )
    rows = await cursor.fetchall()
    return [
        EpisodeStatus(
            episode_id=row[0],
            title=row[1],
            download_status=row[2],
            skip_reason=row[3],
            transcription_status=row[4],
            index_status=row[5],
        )
        for row in rows
    ]
