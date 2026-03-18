"""Hermes lecture management — discard, restore, purge, pipeline status."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import aiosqlite

    from sophia.domain.ports import KnowledgeStore

log = structlog.get_logger()


@dataclass
class EpisodeStatus:
    episode_id: str
    title: str
    download_status: str
    skip_reason: str | None
    transcription_status: str | None
    index_status: str | None


async def discard_episode(db: aiosqlite.Connection, module_id: int, episode_id: str) -> bool:
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


async def restore_episode(db: aiosqlite.Connection, module_id: int, episode_id: str) -> bool:
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


async def get_pipeline_status(db: aiosqlite.Connection, module_id: int) -> list[EpisodeStatus]:
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


@dataclass
class PurgeResult:
    """Counts of items removed during a purge operation."""

    knowledge_chunks: int = 0
    transcript_segments: int = 0
    transcriptions: int = 0
    knowledge_index: int = 0


async def purge_episode(
    db: aiosqlite.Connection,
    store: KnowledgeStore,
    module_id: int,
    episode_id: str,
) -> PurgeResult:
    """Remove indexed content for an episode. Preserves the download record and audio file."""
    # Ownership check: episode must belong to this module
    cursor = await db.execute(
        "SELECT 1 FROM lecture_downloads WHERE episode_id = ? AND module_id = ?",
        (episode_id, module_id),
    )
    if not await cursor.fetchone():
        return PurgeResult()

    # Delete from knowledge_index (has module_id column)
    cursor = await db.execute(
        "DELETE FROM knowledge_index WHERE episode_id = ? AND module_id = ?",
        (episode_id, module_id),
    )
    ki_count = cursor.rowcount

    # Delete transcript segments (no module_id — scope via subquery)
    cursor = await db.execute(
        """DELETE FROM transcript_segments
           WHERE episode_id = ?
             AND episode_id IN (
                 SELECT episode_id FROM transcriptions WHERE module_id = ?
             )""",
        (episode_id, module_id),
    )
    seg_count = cursor.rowcount

    # Delete transcription record (has module_id column)
    cursor = await db.execute(
        "DELETE FROM transcriptions WHERE episode_id = ? AND module_id = ?",
        (episode_id, module_id),
    )
    tx_count = cursor.rowcount

    await db.commit()

    # Delete chunks from vector store
    chunk_count = store.delete_episode(episode_id)

    result = PurgeResult(
        knowledge_chunks=chunk_count,
        transcript_segments=seg_count,
        transcriptions=tx_count,
        knowledge_index=ki_count,
    )
    log.info(
        "episode_purged",
        episode_id=episode_id,
        module_id=module_id,
        **{
            "knowledge_chunks": result.knowledge_chunks,
            "transcript_segments": result.transcript_segments,
            "transcriptions": result.transcriptions,
            "knowledge_index": result.knowledge_index,
        },
    )
    return result
