"""Topics per lecture — which lectures were read, which topics each one gave.

Before #128 a course's topics came from one model call over roughly twelve
minutes of transcript, so every lecture after the first contributed nothing,
and re-processing deleted the whole set with the ratings that hung off it.
Here each lecture is read on its own and its outcome is recorded in
``topic_extractions``, so a second run reads only the lectures it has not
seen and a lecture that failed is retried with its reason on show. Each topic
stays one row per course in ``topic_mappings``, the key ratings and reviews
attach to; ``topic_origins`` is what says which lectures it came from.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.adapters.topic_extractor import LLMTopicExtractor
from sophia.domain.errors import TopicExtractionError
from sophia.domain.models import TopicSource
from sophia.infra.engine import affected_rows, commit_unit
from sophia.infra.schema import (
    confidence_ratings,
    lecture_downloads,
    lecture_modules,
    review_schedule,
    topic_extractions,
    topic_mappings,
    topic_origins,
    transcript_segments,
    transcriptions,
)
from sophia.services.hermes_episodes import course_module_ids_query, episode_title
from sophia.services.hermes_setup import load_hermes_config

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# Per lecture, not per course: a ninety-minute lecture is around 60 000
# characters of transcript, and the model reads a representative sample of it
# rather than its first twelve minutes.
MAX_LECTURE_CHARS = 12_000

# Gemini's free tier answers 503 for minutes at a time (2026-10-09, ~20 min).
# A lecture is retried a few times with widening gaps before it is marked
# failed, and only on errors that read as the service being busy.
RETRY_DELAYS_S: tuple[float, ...] = (5.0, 15.0, 45.0)
_TRANSIENT_MARKERS = ("503", "429", "unavailable", "overloaded", "high demand", "timed out")


@dataclass(frozen=True, slots=True)
class LectureTopicResult:
    """Outcome of topic extraction for one lecture."""

    episode_id: str
    title: str
    status: str  # "completed", "skipped", "failed"
    topics: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TopicOrigin:
    """A lecture a topic was extracted from, as the topic list names it."""

    episode_id: str
    title: str
    lecture_number: int | None


@dataclass(frozen=True, slots=True)
class _PendingLecture:
    episode_id: str
    title: str


def create_topic_extractor(app: AppContainer) -> LLMTopicExtractor:
    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        raise TopicExtractionError("Hermes not configured — run: sophia hermes setup")
    return LLMTopicExtractor(config.llm)


async def extract_topics_per_lecture(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    *,
    module_id: int | None = None,
    force: bool = False,
    on_progress: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[LectureTopicResult]:
    """Extract topics from every lecture of the course that has none yet.

    ``module_id`` narrows the run to one of the course's modules; ``force``
    reads every lecture again, replacing what it contributed last time. Each
    lecture's outcome is committed as it is known, and a lecture whose model
    call fails is marked failed with the reason and left for the next run
    rather than stopping the others.
    """
    if force:
        await _forget_extractions(session, course_id, module_id)
    lectures = await _pending_lectures(session, course_id, module_id)
    if not lectures:
        return []

    course_name = await _course_name(session, course_id)
    extractor: LLMTopicExtractor | None = None
    results: list[LectureTopicResult] = []
    for lecture in lectures:
        if cancel_check and cancel_check():
            log.info("topics_cancelled", course_id=course_id, completed=len(results))
            break
        if on_progress:
            on_progress(lecture.title)
        if extractor is None:
            extractor = create_topic_extractor(app)
        result = await _extract_lecture(session, extractor, course_id, course_name, lecture)
        await commit_unit(session)
        results.append(result)

    if any(result.status == "completed" for result in results):
        from sophia.services.athena_reconciliation import reconcile_manual_topics

        await reconcile_manual_topics(session, course_id)
    log.info(
        "lecture_topics_extracted",
        course_id=course_id,
        lectures=len(results),
        failed=sum(result.status == "failed" for result in results),
    )
    return results


async def _extract_lecture(
    session: AsyncSession,
    extractor: LLMTopicExtractor,
    course_id: int,
    course_name: str,
    lecture: _PendingLecture,
) -> LectureTopicResult:
    text = await _lecture_text(session, lecture.episode_id)
    await _mark(session, lecture.episode_id, course_id, "processing")
    if not text:
        await _mark(session, lecture.episode_id, course_id, "completed", topic_count=0)
        return LectureTopicResult(lecture.episode_id, lecture.title, "completed")

    try:
        labels = await _extract_with_retry(extractor, text, course_name, lecture.title)
    except TopicExtractionError as exc:
        await _mark(session, lecture.episode_id, course_id, "failed", error=str(exc))
        log.error("lecture_topics_failed", episode_id=lecture.episode_id, error=str(exc))
        return LectureTopicResult(lecture.episode_id, lecture.title, "failed", error=str(exc))

    await _store_lecture_topics(session, course_id, lecture.episode_id, labels)
    await _mark(session, lecture.episode_id, course_id, "completed", topic_count=len(labels))
    log.info("lecture_topics_stored", episode_id=lecture.episode_id, count=len(labels))
    return LectureTopicResult(lecture.episode_id, lecture.title, "completed", tuple(labels))


async def _extract_with_retry(
    extractor: LLMTopicExtractor,
    text: str,
    course_name: str,
    lecture_title: str,
) -> list[str]:
    content = f"Lecture: {lecture_title}\n\n{text}" if lecture_title else text
    for attempt, delay in enumerate((*RETRY_DELAYS_S, None)):
        try:
            return await extractor.extract_topics(content, course_context=course_name)
        except TopicExtractionError as exc:
            if delay is None or not _is_transient(exc):
                raise
            log.warning(
                "lecture_topics_retry",
                lecture=lecture_title,
                attempt=attempt + 1,
                retry_in_s=delay,
                error=str(exc),
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable: the last attempt either returns or raises")


def _is_transient(exc: TopicExtractionError) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_MARKERS)


async def _pending_lectures(
    session: AsyncSession,
    course_id: int,
    module_id: int | None,
) -> list[_PendingLecture]:
    """Completed transcripts of the course's modules with no completed extraction."""
    done = select(topic_extractions.c.episode_id).where(
        topic_extractions.c.status == "completed",
    )
    query = (
        select(transcriptions.c.episode_id, episode_title().label("title"))
        .select_from(
            transcriptions.outerjoin(
                lecture_downloads,
                lecture_downloads.c.episode_id == transcriptions.c.episode_id,
            )
        )
        .where(
            transcriptions.c.status == "completed",
            transcriptions.c.episode_id.not_in(done),
        )
        .order_by(
            lecture_downloads.c.lecture_number.asc().nullslast(),
            transcriptions.c.episode_id,
        )
    )
    if module_id is not None:
        query = query.where(transcriptions.c.module_id == module_id)
    else:
        query = query.where(transcriptions.c.module_id.in_(course_module_ids_query(course_id)))
    rows = (await session.execute(query)).all()
    return [_PendingLecture(row.episode_id, row.title) for row in rows]


async def _lecture_text(session: AsyncSession, episode_id: str) -> str:
    """A representative sample of the lecture, within the per-lecture budget.

    Sampled evenly across the lecture rather than cut at the budget, so the
    second half of a long lecture is read as much as the first.
    """
    texts = list(
        await session.scalars(
            select(transcript_segments.c.text)
            .where(transcript_segments.c.episode_id == episode_id)
            .order_by(transcript_segments.c.segment_index)
        )
    )
    total = sum(len(text) + 1 for text in texts)
    if total <= MAX_LECTURE_CHARS:
        return " ".join(texts)
    step = max(1, -(-total // MAX_LECTURE_CHARS))
    sampled: list[str] = []
    budget = MAX_LECTURE_CHARS
    for text in texts[::step]:
        if len(text) + 1 > budget:
            break
        sampled.append(text)
        budget -= len(text) + 1
    return " ".join(sampled)


async def _course_name(session: AsyncSession, course_id: int) -> str:
    name = await session.scalar(
        select(lecture_modules.c.course_name)
        .where(lecture_modules.c.course_id == str(course_id))
        .limit(1)
    )
    return name or ""


async def _mark(
    session: AsyncSession,
    episode_id: str,
    course_id: int,
    status: str,
    *,
    topic_count: int = 0,
    error: str | None = None,
) -> None:
    extracted_at = datetime.now(UTC) if status == "completed" else None
    statement = pg_insert(topic_extractions).values(
        episode_id=episode_id,
        course_id=course_id,
        status=status,
        topic_count=topic_count,
        error=error,
        extracted_at=extracted_at,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[topic_extractions.c.episode_id],
            set_={
                "course_id": statement.excluded.course_id,
                "status": statement.excluded.status,
                "topic_count": statement.excluded.topic_count,
                "error": statement.excluded.error,
                "extracted_at": statement.excluded.extracted_at,
            },
        )
    )


async def _store_lecture_topics(
    session: AsyncSession,
    course_id: int,
    episode_id: str,
    labels: list[str],
) -> None:
    """One topic row per course, however many lectures mention it; one origin per lecture."""
    await session.execute(
        delete(topic_origins).where(
            topic_origins.c.course_id == course_id,
            topic_origins.c.episode_id == episode_id,
        )
    )
    for label in labels:
        await session.execute(
            pg_insert(topic_mappings)
            .values(topic=label, course_id=course_id, source=TopicSource.LECTURE.value)
            .on_conflict_do_nothing(
                index_elements=[
                    topic_mappings.c.topic,
                    topic_mappings.c.course_id,
                    topic_mappings.c.source,
                ]
            )
        )
        await session.execute(
            pg_insert(topic_origins)
            .values(topic=label, course_id=course_id, episode_id=episode_id)
            .on_conflict_do_nothing()
        )
    await _refresh_frequencies(session, course_id)


async def _refresh_frequencies(session: AsyncSession, course_id: int) -> None:
    """A lecture topic's frequency is the number of lectures it came from."""
    origin_count = (
        select(func.count())
        .where(
            topic_origins.c.topic == topic_mappings.c.topic,
            topic_origins.c.course_id == topic_mappings.c.course_id,
        )
        .scalar_subquery()
    )
    await session.execute(
        update(topic_mappings)
        .where(
            topic_mappings.c.course_id == course_id,
            topic_mappings.c.source == TopicSource.LECTURE.value,
            exists().where(
                topic_origins.c.topic == topic_mappings.c.topic,
                topic_origins.c.course_id == topic_mappings.c.course_id,
            ),
        )
        .values(frequency=origin_count)
    )


async def _forget_extractions(
    session: AsyncSession,
    course_id: int,
    module_id: int | None,
) -> None:
    """Drop the record of past runs so every lecture is read again."""
    scope = (
        transcriptions.c.module_id == module_id
        if module_id is not None
        else transcriptions.c.module_id.in_(course_module_ids_query(course_id))
    )
    episodes = select(transcriptions.c.episode_id).where(scope)
    await session.execute(
        delete(topic_extractions).where(
            topic_extractions.c.course_id == course_id,
            topic_extractions.c.episode_id.in_(episodes),
        )
    )
    await session.execute(
        delete(topic_origins).where(
            topic_origins.c.course_id == course_id,
            topic_origins.c.episode_id.in_(episodes),
        )
    )


async def drop_unrated_orphans(session: AsyncSession, course_id: int) -> int:
    """Remove lecture topics no lecture produced that the student never touched.

    After a forced re-extraction a topic the model no longer names has no
    origin left. One the student rated or has a review for stays, because
    those rows are keyed by its text and would otherwise dangle (#128).
    """
    has_origin = exists().where(
        topic_origins.c.topic == topic_mappings.c.topic,
        topic_origins.c.course_id == topic_mappings.c.course_id,
    )
    rated = exists().where(
        confidence_ratings.c.topic == topic_mappings.c.topic,
        confidence_ratings.c.course_id == topic_mappings.c.course_id,
    )
    reviewed = exists().where(
        review_schedule.c.topic == topic_mappings.c.topic,
        review_schedule.c.course_id == topic_mappings.c.course_id,
    )
    result = await session.execute(
        delete(topic_mappings).where(
            topic_mappings.c.course_id == course_id,
            topic_mappings.c.source == TopicSource.LECTURE.value,
            ~has_origin,
            ~rated,
            ~reviewed,
        )
    )
    dropped = affected_rows(result)
    if dropped:
        log.info("stale_lecture_topics_dropped", course_id=course_id, count=dropped)
    return dropped


async def get_topic_origins(
    session: AsyncSession,
    course_id: int,
) -> dict[str, list[TopicOrigin]]:
    """The lectures each of the course's topics came from, by topic text."""
    rows = (
        await session.execute(
            select(
                topic_origins.c.topic,
                topic_origins.c.episode_id,
                func.coalesce(
                    lecture_downloads.c.title, func.nullif(transcriptions.c.title, ""), ""
                ).label("title"),
                lecture_downloads.c.lecture_number,
            )
            .select_from(
                topic_origins.outerjoin(
                    lecture_downloads,
                    lecture_downloads.c.episode_id == topic_origins.c.episode_id,
                ).outerjoin(
                    transcriptions,
                    transcriptions.c.episode_id == topic_origins.c.episode_id,
                )
            )
            .where(topic_origins.c.course_id == course_id)
            .order_by(
                topic_origins.c.topic,
                lecture_downloads.c.lecture_number.asc().nullslast(),
                topic_origins.c.episode_id,
            )
        )
    ).all()
    origins: dict[str, list[TopicOrigin]] = {}
    for row in rows:
        origins.setdefault(row.topic, []).append(
            TopicOrigin(row.episode_id, row.title, row.lecture_number)
        )
    return origins


async def count_failed_extractions(session: AsyncSession, course_id: int) -> int:
    return (
        await session.scalar(
            select(func.count()).where(
                topic_extractions.c.course_id == course_id,
                topic_extractions.c.status == "failed",
            )
        )
        or 0
    )
