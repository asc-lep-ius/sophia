"""Hermes lecture management — discard, restore, purge, pipeline status."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, func, select, update

from sophia.infra.engine import affected_rows
from sophia.infra.schema import (
    knowledge_index,
    lecture_downloads,
    topic_lecture_links,
    transcript_segments,
    transcriptions,
)

if TYPE_CHECKING:
    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

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


async def assign_lecture_numbers(session: AsyncSession, module_id: int) -> None:
    """Assign lecture_number to all episodes in a module.

    Strategy: parse from title first, then fill gaps by created_at ordering.
    """
    rows = (
        await session.execute(
            select(lecture_downloads.c.episode_id, lecture_downloads.c.title)
            .where(lecture_downloads.c.module_id == module_id)
            .order_by(lecture_downloads.c.created_at)
        )
    ).all()

    # Phase 1: titles that parse → fixed numbers
    inferred: dict[str, int] = {}
    unparsed: list[str] = []
    for row in rows:
        num = infer_lecture_number(row.title)
        if num is not None:
            inferred[row.episode_id] = num
        else:
            unparsed.append(row.episode_id)

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
        await session.execute(
            update(lecture_downloads)
            .where(lecture_downloads.c.episode_id == episode_id)
            .values(lecture_number=num)
        )
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


async def _set_episode_state(
    session: AsyncSession,
    module_id: int,
    episode_id: str,
    *,
    guard: ColumnElement[bool],
    values: dict[str, object],
) -> bool:
    """Apply a guarded state change to one episode, reporting whether it applied."""
    result = await session.execute(
        update(lecture_downloads)
        .where(
            lecture_downloads.c.episode_id == episode_id,
            lecture_downloads.c.module_id == module_id,
            guard,
        )
        .values(**values)
    )
    return affected_rows(result) > 0


async def discard_episode(session: AsyncSession, module_id: int, episode_id: str) -> bool:
    """Mark an episode as discarded. Returns True if updated, False if not found."""
    updated = await _set_episode_state(
        session,
        module_id,
        episode_id,
        guard=lecture_downloads.c.status.in_(("completed", "skipped", "failed")),
        values={"status": "discarded"},
    )
    if updated:
        log.info("episode_discarded", episode_id=episode_id, module_id=module_id)
    return updated


async def restore_episode(session: AsyncSession, module_id: int, episode_id: str) -> bool:
    """Restore a discarded episode back to queued. Returns True if restored."""
    restored = await _set_episode_state(
        session,
        module_id,
        episode_id,
        guard=lecture_downloads.c.status == "discarded",
        values={"status": "queued"},
    )
    if restored:
        log.info("episode_restored", episode_id=episode_id, module_id=module_id)
    return restored


async def mark_missed(session: AsyncSession, module_id: int, episode_id: str) -> bool:
    """Mark a lecture as missed by the student. Returns True if updated."""
    updated = await _set_episode_state(
        session,
        module_id,
        episode_id,
        guard=lecture_downloads.c.missed_at.is_(None),
        values={"missed_at": datetime.now(UTC)},
    )
    if updated:
        log.info("episode_marked_missed", episode_id=episode_id, module_id=module_id)
    return updated


async def unmark_missed(session: AsyncSession, module_id: int, episode_id: str) -> bool:
    """Remove missed mark from a lecture. Returns True if updated."""
    updated = await _set_episode_state(
        session,
        module_id,
        episode_id,
        guard=lecture_downloads.c.missed_at.is_not(None),
        values={"missed_at": None},
    )
    if updated:
        log.info("episode_unmarked_missed", episode_id=episode_id, module_id=module_id)
    return updated


def _episode_status_query(module_id: int):
    """Per-episode pipeline state, joined across download, transcription, index."""
    return (
        select(
            lecture_downloads.c.episode_id,
            lecture_downloads.c.title,
            lecture_downloads.c.status.label("download_status"),
            lecture_downloads.c.skip_reason,
            transcriptions.c.status.label("transcription_status"),
            knowledge_index.c.status.label("index_status"),
            lecture_downloads.c.lecture_number,
            lecture_downloads.c.missed_at,
        )
        .select_from(lecture_downloads)
        .outerjoin(
            transcriptions,
            transcriptions.c.episode_id == lecture_downloads.c.episode_id,
        )
        .outerjoin(
            knowledge_index,
            knowledge_index.c.episode_id == lecture_downloads.c.episode_id,
        )
        .where(lecture_downloads.c.module_id == module_id)
    )


def _row_to_episode_status(row: Row[tuple[object, ...]]) -> EpisodeStatus:
    return EpisodeStatus(
        episode_id=row.episode_id,
        title=row.title,
        download_status=row.download_status,
        skip_reason=row.skip_reason,
        transcription_status=row.transcription_status,
        index_status=row.index_status,
        lecture_number=row.lecture_number,
        missed_at=row.missed_at.isoformat() if row.missed_at else None,
    )


async def get_missed_episodes(session: AsyncSession, module_id: int) -> list[EpisodeStatus]:
    """Return all episodes marked as missed for a module."""
    query = (
        _episode_status_query(module_id)
        .where(
            lecture_downloads.c.missed_at.is_not(None),
        )
        .order_by(
            lecture_downloads.c.lecture_number.asc().nullslast(),
            lecture_downloads.c.created_at.asc(),
        )
    )
    return [_row_to_episode_status(row) for row in (await session.execute(query)).all()]


@dataclass
class CatchUpInfo:
    """Topics the student missed, grouped by exposure."""

    missed_only_topics: list[str]
    partial_topics: list[str]
    missed_episodes: list[EpisodeStatus]


async def get_catch_up_info(
    session: AsyncSession,
    module_id: int,
) -> CatchUpInfo:
    """Analyze which topics the student missed based on marked lectures.

    Groups topics into:
    - missed_only: topics covered ONLY in missed lectures (highest-priority gaps)
    - partial: topics covered in both missed AND attended lectures
    """

    async def episode_ids(*, missed: bool) -> list[str]:
        missed_at = lecture_downloads.c.missed_at
        query = select(lecture_downloads.c.episode_id).where(
            lecture_downloads.c.module_id == module_id,
            missed_at.is_not(None) if missed else missed_at.is_(None),
        )
        return list((await session.scalars(query)).all())

    async def topics_for(episodes: list[str]) -> set[str]:
        if not episodes:
            return set()
        query = (
            select(topic_lecture_links.c.topic)
            .where(topic_lecture_links.c.episode_id.in_(episodes))
            .distinct()
        )
        return set((await session.scalars(query)).all())

    missed_ids = await episode_ids(missed=True)
    if not missed_ids:
        return CatchUpInfo(missed_only_topics=[], partial_topics=[], missed_episodes=[])

    missed_episodes = await get_missed_episodes(session, module_id)
    missed_topics = await topics_for(missed_ids)
    if not missed_topics:
        return CatchUpInfo(
            missed_only_topics=[],
            partial_topics=[],
            missed_episodes=missed_episodes,
        )

    attended_topics = await topics_for(await episode_ids(missed=False))
    return CatchUpInfo(
        missed_only_topics=sorted(missed_topics - attended_topics),
        partial_topics=sorted(missed_topics & attended_topics),
        missed_episodes=missed_episodes,
    )


async def get_pipeline_status(session: AsyncSession, module_id: int) -> list[EpisodeStatus]:
    """Query per-episode pipeline state for a module."""
    query = _episode_status_query(module_id).order_by(lecture_downloads.c.title)
    return [_row_to_episode_status(row) for row in (await session.execute(query)).all()]


@dataclass
class PurgeResult:
    """Counts of items removed during a purge operation."""

    knowledge_chunks: int = 0
    transcript_segments: int = 0
    transcriptions: int = 0
    knowledge_index: int = 0


async def purge_episode(
    session: AsyncSession,
    store: KnowledgeStore,
    module_id: int,
    episode_id: str,
) -> PurgeResult:
    """Remove indexed content for an episode. Preserves the download record and audio file."""
    # Ownership check: episode must belong to this module
    owned = await session.scalar(
        select(lecture_downloads.c.episode_id).where(
            lecture_downloads.c.episode_id == episode_id,
            lecture_downloads.c.module_id == module_id,
        )
    )
    if owned is None:
        return PurgeResult()

    # Delete from knowledge_index (has module_id column)
    ki_count = affected_rows(
        await session.execute(
            delete(knowledge_index).where(
                knowledge_index.c.episode_id == episode_id,
                knowledge_index.c.module_id == module_id,
            )
        )
    )

    # Delete transcript segments (no module_id — scope via subquery)
    owning_transcriptions = select(transcriptions.c.episode_id).where(
        transcriptions.c.module_id == module_id,
    )
    seg_count = affected_rows(
        await session.execute(
            delete(transcript_segments).where(
                transcript_segments.c.episode_id == episode_id,
                transcript_segments.c.episode_id.in_(owning_transcriptions),
            )
        )
    )

    # Delete transcription record (has module_id column)
    tx_count = affected_rows(
        await session.execute(
            delete(transcriptions).where(
                transcriptions.c.episode_id == episode_id,
                transcriptions.c.module_id == module_id,
            )
        )
    )

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
    session: AsyncSession,
    store: KnowledgeStore,
    module_id: int,
) -> PurgeResult:
    """Purge all indexed content for every episode in a module.

    Calls purge_episode for each episode and accumulates results.
    Preserves download records and audio files (same as single-episode purge).
    """
    episode_ids = list(
        (
            await session.scalars(
                select(lecture_downloads.c.episode_id).where(
                    lecture_downloads.c.module_id == module_id,
                )
            )
        ).all()
    )
    if not episode_ids:
        return PurgeResult()

    total = PurgeResult()
    for ep_id in episode_ids:
        result = await purge_episode(session, store, module_id, ep_id)
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


async def get_episode_count(session: AsyncSession, module_id: int) -> int:
    """Return the number of episodes for a module."""
    total = await session.scalar(
        select(func.count())
        .select_from(lecture_downloads)
        .where(lecture_downloads.c.module_id == module_id)
    )
    return total or 0
