"""Hermes lecture management — discard, restore, purge, pipeline status."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import aiosqlite

    from sophia.domain.ports import KnowledgeStore

log = structlog.get_logger()

_LECTURE_NUM_RE = re.compile(
    r"(?:lecture|vorlesung|vo|lva|#)\s*(\d+)",
    re.IGNORECASE,
)


def infer_lecture_number(title: str) -> int | None:
    """Parse lecture number from title. Returns None if not parseable."""
    m = _LECTURE_NUM_RE.search(title)
    return int(m.group(1)) if m else None


async def assign_lecture_numbers(db: aiosqlite.Connection, module_id: int) -> None:
    """Assign lecture_number to all episodes in a module.

    Strategy: parse from title first, then fill gaps by created_at ordering.
    """
    cursor = await db.execute(
        "SELECT episode_id, title, created_at FROM lecture_downloads "
        "WHERE module_id = ? ORDER BY created_at",
        (module_id,),
    )
    rows = await cursor.fetchall()

    # Phase 1: titles that parse → fixed numbers
    inferred: dict[str, int] = {}
    unparsed: list[str] = []
    for episode_id, title, _created_at in rows:
        num = infer_lecture_number(title)
        if num is not None:
            inferred[episode_id] = num
        else:
            unparsed.append(episode_id)

    # Phase 2: gap-fill for unparsed episodes in creation order
    used = set(inferred.values())
    counter = 1
    for episode_id in unparsed:
        while counter in used:
            counter += 1
        inferred[episode_id] = counter
        used.add(counter)
        counter += 1

    # Phase 3: persist
    for episode_id, num in inferred.items():
        await db.execute(
            "UPDATE lecture_downloads SET lecture_number = ? WHERE episode_id = ?",
            (num, episode_id),
        )
    await db.commit()
    log.info("lecture_numbers_assigned", module_id=module_id, count=len(inferred))


@dataclass
class EpisodeStatus:
    episode_id: str
    title: str
    download_status: str
    skip_reason: str | None
    transcription_status: str | None
    index_status: str | None
    lecture_number: int | None = None
    missed_at: str | None = None


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


async def mark_missed(db: aiosqlite.Connection, module_id: int, episode_id: str) -> bool:
    """Mark a lecture as missed by the student. Returns True if updated."""
    cursor = await db.execute(
        """UPDATE lecture_downloads SET missed_at = CURRENT_TIMESTAMP
           WHERE episode_id = ? AND module_id = ? AND missed_at IS NULL""",
        (episode_id, module_id),
    )
    await db.commit()
    updated = cursor.rowcount > 0
    if updated:
        log.info("episode_marked_missed", episode_id=episode_id, module_id=module_id)
    return updated


async def unmark_missed(db: aiosqlite.Connection, module_id: int, episode_id: str) -> bool:
    """Remove missed mark from a lecture. Returns True if updated."""
    cursor = await db.execute(
        """UPDATE lecture_downloads SET missed_at = NULL
           WHERE episode_id = ? AND module_id = ? AND missed_at IS NOT NULL""",
        (episode_id, module_id),
    )
    await db.commit()
    updated = cursor.rowcount > 0
    if updated:
        log.info("episode_unmarked_missed", episode_id=episode_id, module_id=module_id)
    return updated


async def get_missed_episodes(db: aiosqlite.Connection, module_id: int) -> list[EpisodeStatus]:
    """Return all episodes marked as missed for a module."""
    cursor = await db.execute(
        """SELECT
               ld.episode_id,
               ld.title,
               ld.status,
               ld.skip_reason,
               t.status,
               ki.status,
               ld.lecture_number,
               ld.missed_at
           FROM lecture_downloads ld
           LEFT JOIN transcriptions t ON t.episode_id = ld.episode_id
           LEFT JOIN knowledge_index ki ON ki.episode_id = ld.episode_id
           WHERE ld.module_id = ? AND ld.missed_at IS NOT NULL
           ORDER BY ld.lecture_number ASC NULLS LAST, ld.created_at ASC""",
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
            lecture_number=row[6],
            missed_at=row[7],
        )
        for row in rows
    ]


@dataclass
class CatchUpInfo:
    """Topics the student missed, grouped by exposure."""

    missed_only_topics: list[str]
    partial_topics: list[str]
    missed_episodes: list[EpisodeStatus]


async def get_catch_up_info(
    db: aiosqlite.Connection,
    module_id: int,
) -> CatchUpInfo:
    """Analyze which topics the student missed based on marked lectures.

    Groups topics into:
    - missed_only: topics covered ONLY in missed lectures (highest-priority gaps)
    - partial: topics covered in both missed AND attended lectures
    """
    cursor = await db.execute(
        "SELECT episode_id FROM lecture_downloads WHERE module_id = ? AND missed_at IS NOT NULL",
        (module_id,),
    )
    missed_ids = [row[0] for row in await cursor.fetchall()]
    if not missed_ids:
        return CatchUpInfo(missed_only_topics=[], partial_topics=[], missed_episodes=[])

    missed_episodes = await get_missed_episodes(db, module_id)

    placeholders = ",".join("?" * len(missed_ids))
    cursor = await db.execute(
        f"SELECT DISTINCT topic FROM topic_lecture_links WHERE episode_id IN ({placeholders})",  # noqa: S608
        missed_ids,
    )
    missed_topics = {row[0] for row in await cursor.fetchall()}

    if not missed_topics:
        return CatchUpInfo(
            missed_only_topics=[],
            partial_topics=[],
            missed_episodes=missed_episodes,
        )

    cursor = await db.execute(
        "SELECT episode_id FROM lecture_downloads WHERE module_id = ? AND missed_at IS NULL",
        (module_id,),
    )
    attended_ids = [row[0] for row in await cursor.fetchall()]

    attended_topics: set[str] = set()
    if attended_ids:
        placeholders = ",".join("?" * len(attended_ids))
        cursor = await db.execute(
            f"SELECT DISTINCT topic FROM topic_lecture_links WHERE episode_id IN ({placeholders})",  # noqa: S608
            attended_ids,
        )
        attended_topics = {row[0] for row in await cursor.fetchall()}

    missed_only = sorted(missed_topics - attended_topics)
    partial = sorted(missed_topics & attended_topics)

    return CatchUpInfo(
        missed_only_topics=missed_only,
        partial_topics=partial,
        missed_episodes=missed_episodes,
    )


async def get_pipeline_status(db: aiosqlite.Connection, module_id: int) -> list[EpisodeStatus]:
    """Query per-episode pipeline state for a module."""
    cursor = await db.execute(
        """SELECT
               ld.episode_id,
               ld.title,
               ld.status,
               ld.skip_reason,
               t.status,
               ki.status,
               ld.lecture_number,
               ld.missed_at
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
            lecture_number=row[6],
            missed_at=row[7],
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


async def purge_module(
    db: aiosqlite.Connection,
    store: KnowledgeStore,
    module_id: int,
) -> PurgeResult:
    """Purge all indexed content for every episode in a module.

    Calls purge_episode for each episode and accumulates results.
    Preserves download records and audio files (same as single-episode purge).
    """
    cursor = await db.execute(
        "SELECT episode_id FROM lecture_downloads WHERE module_id = ?",
        (module_id,),
    )
    episode_ids = [row[0] for row in await cursor.fetchall()]
    if not episode_ids:
        return PurgeResult()

    total = PurgeResult()
    for ep_id in episode_ids:
        result = await purge_episode(db, store, module_id, ep_id)
        total.knowledge_chunks += result.knowledge_chunks
        total.transcript_segments += result.transcript_segments
        total.transcriptions += result.transcriptions
        total.knowledge_index += result.knowledge_index

    log.info(
        "module_purged",
        module_id=module_id,
        episodes=len(episode_ids),
        **{
            "knowledge_chunks": total.knowledge_chunks,
            "transcript_segments": total.transcript_segments,
            "transcriptions": total.transcriptions,
            "knowledge_index": total.knowledge_index,
        },
    )
    return total


async def get_episode_count(db: aiosqlite.Connection, module_id: int) -> int:
    """Return the number of episodes for a module."""
    cursor = await db.execute(
        "SELECT COUNT(*) FROM lecture_downloads WHERE module_id = ?",
        (module_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else 0
