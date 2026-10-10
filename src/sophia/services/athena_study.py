"""Athena study service — topic extraction, study sessions, and flashcards."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import case, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.domain.errors import EmbeddingError, TopicExtractionError
from sophia.domain.learning import QuestionFallbackReason
from sophia.domain.models import (
    CardReviewAttempt,
    FlashcardSource,
    KnowledgeChunk,
    SelfExplanation,
    StudentFlashcard,
    TopicMapping,
    TopicSource,
)
from sophia.infra.engine import affected_rows
from sophia.infra.schema import (
    card_review_attempts,
    course_materials,
    self_explanations,
    student_flashcards,
    topic_lecture_links,
    topic_mappings,
)
from sophia.services.athena_session import (
    complete_study_session as complete_study_session,
)
from sophia.services.athena_session import (
    get_study_sessions as get_study_sessions,
)
from sophia.services.athena_session import (
    run_interactive_session as run_interactive_session,
)
from sophia.services.athena_session import (
    save_flashcard as save_flashcard,
)
from sophia.services.athena_session import (
    start_study_session as start_study_session,
)
from sophia.services.athena_topics import (
    create_topic_extractor as _create_topic_extractor,
)
from sophia.services.athena_topics import (
    drop_unrated_orphans,
    extract_topics_per_lecture,
)
from sophia.services.hermes_episodes import (
    course_episode_ids_query,
    episode_titles_query,
)
from sophia.services.hermes_index import knowledge_store, query_embedder
from sophia.services.idempotency import insert_or_fetch_row

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Row, Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.adapters.knowledge_store import ChromaKnowledgeStore
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


async def _get_episode_ids(session: AsyncSession, course_id: int) -> list[str]:
    """Episode IDs of every module the course owns, to scope ChromaDB searches."""
    return list((await session.scalars(course_episode_ids_query(course_id))).all())


async def _get_material_episode_ids(
    session: AsyncSession,
    course_id: int,
) -> tuple[list[str], dict[str, str]]:
    """Get material episode IDs and a map of episode_id → material name."""
    rows = (
        await session.execute(
            select(course_materials.c.id, course_materials.c.name).where(
                course_materials.c.course_id == course_id,
                course_materials.c.status == "completed",
            )
        )
    ).all()
    ep_ids = [f"mat-{row.id}" for row in rows]
    name_map = {f"mat-{row.id}": row.name for row in rows}
    return ep_ids, name_map


async def _search_material_chunks(
    session: AsyncSession,
    store: ChromaKnowledgeStore,
    query_embedding: list[float],
    course_id: int,
    *,
    n_results: int = 5,
) -> tuple[list[tuple[KnowledgeChunk, float]], dict[str, str]]:
    """Search PDF material chunks for a course. Returns (results, name_map)."""
    mat_ep_ids, name_map = await _get_material_episode_ids(session, course_id)
    if not mat_ep_ids:
        return [], {}
    results: list[tuple[KnowledgeChunk, float]] = await asyncio.to_thread(
        store.search,
        query_embedding,
        n_results=n_results,
        episode_ids=mat_ep_ids,
        source_filter="pdf",
    )
    return results, name_map


async def extract_topics_from_lectures(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    *,
    on_progress: Callable[[str], None] | None = None,
    force: bool = False,
) -> list[TopicMapping]:
    """Extract a course's topics, one lecture at a time, and return its lecture topics.

    Topics are stored under the course, the id the browser reads them by, never
    under one of its Opencast modules (#127). Which modules a course owns is
    what discovery recorded in ``lecture_modules``.

    Each lecture is read on its own and remembered in ``topic_extractions``, so
    a run reads only the lectures no run has read before: with nothing new,
    the model is not called and the stored topics come back as they are (#128).
    Manual topics do not count as read: they share the course key, but no
    extraction produced them, and they are never returned here.

    ``force=True`` reads every lecture again. Topics the student rated or has a
    review for are kept whatever the model says this time; the rest of the
    ones no lecture names any more are dropped.
    """
    await extract_topics_per_lecture(app, session, course_id, force=force, on_progress=on_progress)
    if force:
        await drop_unrated_orphans(session, course_id)
    return [
        topic
        for topic in await get_course_topics(session, course_id)
        if topic.source == TopicSource.LECTURE
    ]


async def link_topics_to_lectures(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    topics: list[str],
    *,
    on_progress: Callable[[str, int], None] | None = None,
) -> dict[str, list[tuple[KnowledgeChunk, float]]]:
    """Cross-reference topics with lecture chunks via semantic search.

    For each topic:
    1. Embed the topic text
    2. Search the KnowledgeStore scoped to the episodes of every module the course owns
    3. Store links in topic_lecture_links table
    4. Return mapping of topic -> [(chunk, score), ...]
    """
    if not topics:
        return {}

    episode_ids = await _get_episode_ids(session, course_id)
    if not episode_ids:
        log.info("no_episodes_for_linking", course_id=course_id)
        return {}

    embedder = query_embedder(app)
    store = knowledge_store(app.settings)

    results: dict[str, list[tuple[KnowledgeChunk, float]]] = {}

    for i, topic in enumerate(topics):
        if on_progress:
            on_progress(topic, i)

        query_embedding: list[float] = await asyncio.to_thread(embedder.embed_query, topic)
        search_results: list[tuple[KnowledgeChunk, float]] = await asyncio.to_thread(
            store.search, query_embedding, n_results=5, episode_ids=episode_ids
        )

        # Also search PDF material chunks
        pdf_results, _ = await _search_material_chunks(
            session, store, query_embedding, course_id, n_results=5
        )
        combined = search_results + pdf_results
        results[topic] = combined

        # Persist links
        for chunk, score in combined:
            statement = pg_insert(topic_lecture_links).values(
                topic=topic,
                course_id=course_id,
                chunk_id=chunk.chunk_id,
                episode_id=chunk.episode_id,
                score=score,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        topic_lecture_links.c.topic,
                        topic_lecture_links.c.course_id,
                        topic_lecture_links.c.chunk_id,
                    ],
                    set_={"score": statement.excluded.score},
                )
            )

    log.info("topics_linked", course_id=course_id, topic_count=len(results))
    return results


async def get_course_topics(
    session: AsyncSession,
    course_id: int,
) -> list[TopicMapping]:
    """Load persisted topics for a course from the database."""
    rows = (
        await session.execute(
            select(topic_mappings)
            .where(topic_mappings.c.course_id == course_id)
            .order_by(topic_mappings.c.frequency.desc(), topic_mappings.c.topic.asc())
        )
    ).all()
    return [
        TopicMapping(
            topic=row.topic,
            course_id=row.course_id,
            source=TopicSource(row.source),
            frequency=row.frequency,
        )
        for row in rows
    ]


async def save_manual_topic(
    session: AsyncSession,
    topic: str,
    course_id: int,
) -> TopicMapping | None:
    """Save a user-entered topic with source='manual'. Returns None if empty/duplicate."""
    stripped = topic.strip()
    if not stripped:
        return None

    result = await session.execute(
        pg_insert(topic_mappings)
        .values(
            topic=stripped,
            course_id=course_id,
            source=TopicSource.MANUAL.value,
            frequency=1,
        )
        .on_conflict_do_nothing(
            index_elements=[
                topic_mappings.c.topic,
                topic_mappings.c.course_id,
                topic_mappings.c.source,
            ]
        )
    )

    if affected_rows(result) == 0:
        log.debug("manual_topic_duplicate", topic=stripped, course_id=course_id)
        return None

    log.info("manual_topic_saved", topic=stripped, course_id=course_id)
    return TopicMapping(topic=stripped, course_id=course_id, source=TopicSource.MANUAL)


# ---------------------------------------------------------------------------
# Question generation (RAG-grounded)
# ---------------------------------------------------------------------------

_FALLBACK_QUESTION = "Explain the concept of {topic} in your own words."


@dataclass(frozen=True, slots=True)
class GroundedQuestion:
    """A practice question and the lecture chunks it was generated from.

    ``sources`` is empty for the template fallback: nothing grounds it, so there
    is nothing to show the learner beside it. ``fallback_reason`` says why, when
    the learner is to be told.
    """

    prompt: str
    sources: tuple[KnowledgeChunk, ...] = ()
    fallback_reason: QuestionFallbackReason | None = None


async def _embed_topic(app: AppContainer, topic: str) -> tuple[ChromaKnowledgeStore, list[float]]:
    """The knowledge store and the topic's query embedding, ready for a scoped search."""
    embedder = query_embedder(app)
    query_embedding = await asyncio.to_thread(embedder.embed_query, topic)
    return knowledge_store(app.settings), query_embedding


async def retrieve_lecture_chunks(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    topic: str,
    *,
    n_results: int = 5,
) -> list[KnowledgeChunk]:
    """The course's lecture transcript chunks most relevant to a topic, best first.

    Searched across every module the course owns. Empty when none of them has
    lecture data; ``EmbeddingError`` when the index cannot be read.
    """
    episode_ids = await _get_episode_ids(session, course_id)
    if not episode_ids:
        return []

    store, query_embedding = await _embed_topic(app, topic)
    results: list[tuple[KnowledgeChunk, float]] = await asyncio.to_thread(
        store.search, query_embedding, n_results=n_results, episode_ids=episode_ids
    )
    return [chunk for chunk, _score in results]


async def get_lecture_context(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    topic: str,
    *,
    n_results: int = 5,
    with_provenance: bool = False,
    include_materials: bool = False,
) -> str:
    """Retrieve concatenated lecture transcript chunks relevant to a topic.

    Uses RAG: embed topic → search ChromaDB scoped to the episodes of every
    module the course owns. Returns empty string if no lecture data is available.

    When ``with_provenance=True`` each chunk is prefixed with
    ``[Title, MM:SS]`` so the reader knows its source and timestamp.

    When ``include_materials=True`` PDF material chunks are also searched
    and appended with ``[PDF: name, chunk N]`` provenance annotations.
    """
    episode_ids = await _get_episode_ids(session, course_id)
    if not episode_ids:
        return ""

    store, query_embedding = await _embed_topic(app, topic)
    search_results: list[tuple[KnowledgeChunk, float]] = await asyncio.to_thread(
        store.search, query_embedding, n_results=n_results, episode_ids=episode_ids
    )

    # Optionally search PDF material chunks
    pdf_results: list[tuple[KnowledgeChunk, float]] = []
    mat_name_map: dict[str, str] = {}
    if include_materials:
        pdf_results, mat_name_map = await _search_material_chunks(
            session, store, query_embedding, course_id, n_results=n_results
        )

    if not with_provenance and not include_materials:
        return "\n\n".join(chunk.text for chunk, _score in search_results)

    if not with_provenance:
        all_texts = [chunk.text for chunk, _ in search_results]
        for chunk, _ in pdf_results:
            mat_name = mat_name_map.get(chunk.episode_id, "PDF")
            all_texts.append(f"[PDF: {mat_name}, chunk {chunk.chunk_index}]\n{chunk.text}")
        return "\n\n".join(all_texts)

    # Build episode→title map for lecture chunks
    ep_ids = list({chunk.episode_id for chunk, _ in search_results})
    title_map: dict[str, str] = {}
    if ep_ids:
        rows = (await session.execute(episode_titles_query(ep_ids))).all()
        title_map = {row.episode_id: row.title for row in rows}

    parts: list[str] = []
    for chunk, _ in search_results:
        mm, ss = divmod(int(chunk.start_time), 60)
        raw_title = title_map.get(chunk.episode_id, "Lecture")
        short = raw_title[:25].rstrip() + "…" if len(raw_title) > 25 else raw_title
        parts.append(f"[{short}, {mm:02d}:{ss:02d}]\n{chunk.text}")

    for chunk, _ in pdf_results:
        mat_name = mat_name_map.get(chunk.episode_id, "PDF")
        parts.append(f"[PDF: {mat_name}, chunk {chunk.chunk_index}]\n{chunk.text}")

    return "\n\n".join(parts)


async def generate_grounded_questions(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    topic: str,
    count: int = 3,
    difficulty: str = "explain",
) -> list[GroundedQuestion]:
    """Generate practice questions for a topic, each with the chunks behind it.

    Uses RAG: embed topic → search lecture chunks → feed to LLM as context.
    Falls back to generic questions if no lecture data or no LLM. The chunks are
    returned rather than dropped because they are what the study surface shows
    at reveal: without them the learner self-grades against nothing.

    An index that cannot be read falls back too, with the reason attached: the
    learner is told why their lectures are missing, never handed a server error.
    """
    fallback = GroundedQuestion(prompt=_FALLBACK_QUESTION.format(topic=topic))
    try:
        chunks = tuple(await retrieve_lecture_chunks(app, session, course_id, topic))
    except EmbeddingError as exc:
        log.warning("lecture_index_unavailable", course_id=course_id, topic=topic, error=str(exc))
        unreadable = GroundedQuestion(
            prompt=fallback.prompt, fallback_reason=QuestionFallbackReason.INDEX_UNAVAILABLE
        )
        return [unreadable] * count

    if not chunks:
        return [fallback] * count

    lecture_context = "\n\n".join(chunk.text for chunk in chunks)
    extractor = _create_topic_extractor(app)
    prompts: list[str] = []
    for _ in range(count):
        try:
            q = await extractor.generate_question(topic, lecture_context, difficulty=difficulty)
            if q and q not in prompts:
                prompts.append(q)
        except TopicExtractionError as exc:
            log.warning("question_generation_failed", topic=topic, error=str(exc))
            break

    questions = [GroundedQuestion(prompt=prompt, sources=chunks) for prompt in prompts]
    return questions + [fallback] * (count - len(questions))


async def generate_study_questions(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    topic: str,
    count: int = 3,
    difficulty: str = "explain",
) -> list[str]:
    """Generate practice question prompts for a topic, grounded in lecture content."""
    questions = await generate_grounded_questions(
        app, session, course_id, topic, count=count, difficulty=difficulty
    )
    return [question.prompt for question in questions]


def _row_to_flashcard(row: Row[tuple[object, ...]]) -> StudentFlashcard:
    return StudentFlashcard(
        id=row.id,
        course_id=row.course_id,
        topic=row.topic,
        front=row.front,
        back=row.back,
        source=FlashcardSource(row.source),
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


async def get_flashcards(
    session: AsyncSession,
    course_id: int,
    topic: str | None = None,
) -> list[StudentFlashcard]:
    """Load flashcards for a course, optionally filtered by topic."""
    query = (
        select(student_flashcards)
        .where(student_flashcards.c.course_id == course_id)
        .order_by(student_flashcards.c.created_at.desc())
    )
    if topic:
        query = query.where(student_flashcards.c.topic == topic)
    return [_row_to_flashcard(row) for row in (await session.execute(query)).all()]


# ---------------------------------------------------------------------------
# Card reviews
# ---------------------------------------------------------------------------


async def save_review_attempt(
    session: AsyncSession,
    flashcard_id: int,
    success: bool,
) -> CardReviewAttempt:
    """Insert a review attempt and return the model."""
    now = datetime.now(UTC)
    attempt_id = (
        await session.execute(
            insert(card_review_attempts)
            .values(flashcard_id=flashcard_id, success=success, reviewed_at=now)
            .returning(card_review_attempts.c.id)
        )
    ).scalar_one()
    return CardReviewAttempt(
        id=attempt_id,
        flashcard_id=flashcard_id,
        success=success,
        reviewed_at=now.isoformat(),
    )


def _review_totals_query(course_id: int, topic: str | None) -> Select[tuple[int, int]]:
    query = (
        select(
            func.count().label("total"),
            func.coalesce(
                func.sum(case((card_review_attempts.c.success, 1), else_=0)),
                0,
            ).label("successes"),
        )
        .select_from(card_review_attempts)
        .join(
            student_flashcards,
            student_flashcards.c.id == card_review_attempts.c.flashcard_id,
        )
        .where(student_flashcards.c.course_id == course_id)
    )
    if topic:
        query = query.where(student_flashcards.c.topic == topic)
    return query


async def get_review_stats(
    session: AsyncSession,
    course_id: int,
    topic: str | None = None,
) -> dict[str, Any]:
    """Get per-topic review stats: total_reviews, success_count, success_rate."""
    row = (await session.execute(_review_totals_query(course_id, topic))).one()
    total = row.total
    success_count = int(row.successes or 0)
    return {
        "total_reviews": total,
        "success_count": success_count,
        "success_rate": success_count / total if total > 0 else 0.0,
    }


async def get_due_cards(
    session: AsyncSession,
    course_id: int,
    topic: str | None = None,
    limit: int = 10,
) -> list[StudentFlashcard]:
    """Get cards due for review — never-reviewed first, then oldest reviewed."""
    last_reviewed = func.max(card_review_attempts.c.reviewed_at)
    query = (
        select(student_flashcards)
        .select_from(student_flashcards)
        .outerjoin(
            card_review_attempts,
            student_flashcards.c.id == card_review_attempts.c.flashcard_id,
        )
        .where(student_flashcards.c.course_id == course_id)
        .group_by(student_flashcards.c.id)
        .order_by(last_reviewed.is_not(None), last_reviewed.asc())
        .limit(limit)
    )
    if topic:
        query = query.where(student_flashcards.c.topic == topic)
    return [_row_to_flashcard(row) for row in (await session.execute(query)).all()]


async def get_failed_review_cards(
    session: AsyncSession,
    course_id: int,
    topic: str | None = None,
    limit: int = 5,
) -> list[StudentFlashcard]:
    """Get cards that were reviewed and answered incorrectly."""
    query = (
        select(student_flashcards)
        .select_from(student_flashcards)
        .join(
            card_review_attempts,
            card_review_attempts.c.flashcard_id == student_flashcards.c.id,
        )
        .where(
            student_flashcards.c.course_id == course_id,
            card_review_attempts.c.success.is_(False),
        )
        .group_by(student_flashcards.c.id)
        .order_by(func.max(card_review_attempts.c.reviewed_at).desc())
        .limit(limit)
    )
    if topic:
        query = query.where(student_flashcards.c.topic == topic)
    return [_row_to_flashcard(row) for row in (await session.execute(query)).all()]


async def update_topic_calibration(
    session: AsyncSession,
    course_id: int,
    topic: str,
) -> None:
    """Compute review success rate and auto-populate confidence actual_score."""
    row = (await session.execute(_review_totals_query(course_id, topic))).one()
    if row.total == 0:
        return

    success_count = int(row.successes or 0)
    success_rate = success_count / row.total

    from sophia.services.athena_confidence import update_actual_score

    await update_actual_score(session, topic, course_id, success_rate)
    log.info(
        "topic_calibration_updated",
        topic=topic,
        course_id=course_id,
        success_rate=success_rate,
    )


# ---------------------------------------------------------------------------
# Self-explanation
# ---------------------------------------------------------------------------

_FULL_SCAFFOLD_PROMPTS = [
    "What fact, rule, or concept did you apply to your answer?",
    "What is different about the correct answer compared to yours?",
    "Give a concrete example that illustrates the correct concept.",
]

_MEDIUM_SCAFFOLD_PROMPTS = [
    "Why was your answer wrong?",
]


async def get_explanation_count(session: AsyncSession, course_id: int) -> int:
    """Count total self-explanations across all topics for a course."""
    total = await session.scalar(
        select(func.count())
        .select_from(self_explanations)
        .join(
            student_flashcards,
            student_flashcards.c.id == self_explanations.c.flashcard_id,
        )
        .where(student_flashcards.c.course_id == course_id)
    )
    return total or 0


def get_scaffold_level(explanation_count: int) -> int:
    """Determine scaffold level based on experience.

    0-9 explanations: level 3 (full scaffolding)
    10-19 explanations: level 1 (minimal scaffolding)
    20+: level 0 (open — student self-regulates)
    """
    if explanation_count < 10:
        return 3
    if explanation_count < 20:
        return 1
    return 0


def get_scaffold_prompts(level: int) -> list[str]:
    """Get the explanation prompts for a given scaffold level."""
    if level >= 3:
        return list(_FULL_SCAFFOLD_PROMPTS)
    if level >= 1:
        return list(_MEDIUM_SCAFFOLD_PROMPTS)
    return []


async def save_self_explanation(
    session: AsyncSession,
    flashcard_id: int,
    student_explanation: str,
    scaffold_level: int,
) -> SelfExplanation:
    """Save a student's self-explanation for a flashcard."""
    now = datetime.now(UTC)
    explanation_id = (
        await session.execute(
            insert(self_explanations)
            .values(
                flashcard_id=flashcard_id,
                student_explanation=student_explanation,
                scaffold_level=scaffold_level,
                created_at=now,
            )
            .returning(self_explanations.c.id)
        )
    ).scalar_one()
    return SelfExplanation(
        id=explanation_id,
        flashcard_id=flashcard_id,
        student_explanation=student_explanation,
        scaffold_level=scaffold_level,
        created_at=now.isoformat(),
    )


async def save_self_explanation_idempotent(
    session: AsyncSession,
    flashcard_id: int,
    student_explanation: str,
    scaffold_level: int,
    *,
    session_id: int,
    user_id: str,
    request_id: str,
) -> tuple[SelfExplanation, bool]:
    """Idempotently save a self-explanation made during a live study session.

    Distinct from :func:`save_self_explanation`, used elsewhere (CLI) with no
    request id to be idempotent on. Returns ``(explanation, is_new)``.
    """
    now = datetime.now(UTC)
    row, is_new = await insert_or_fetch_row(
        session,
        self_explanations,
        {
            "flashcard_id": flashcard_id,
            "student_explanation": student_explanation,
            "scaffold_level": scaffold_level,
            "created_at": now,
            "session_id": session_id,
            "user_id": user_id,
            "request_id": request_id,
        },
        conflict_columns=(
            self_explanations.c.org_id,
            self_explanations.c.session_id,
            self_explanations.c.user_id,
            self_explanations.c.request_id,
        ),
        session_id=session_id,
        user_id=user_id,
        request_id=request_id,
    )
    return (
        SelfExplanation(
            id=row.id,
            flashcard_id=row.flashcard_id,
            student_explanation=row.student_explanation,
            scaffold_level=row.scaffold_level,
            created_at=row.created_at.isoformat() if row.created_at else "",
        ),
        is_new,
    )


async def get_self_explanations(
    session: AsyncSession,
    flashcard_id: int,
) -> list[SelfExplanation]:
    """Get all self-explanations for a flashcard."""
    rows = (
        await session.execute(
            select(self_explanations)
            .where(self_explanations.c.flashcard_id == flashcard_id)
            .order_by(self_explanations.c.created_at.desc())
        )
    ).all()
    return [
        SelfExplanation(
            id=row.id,
            flashcard_id=row.flashcard_id,
            student_explanation=row.student_explanation,
            scaffold_level=row.scaffold_level,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]
