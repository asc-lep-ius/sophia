"""Athena study service — topic extraction, study sessions, and flashcards."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import case, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.adapters.topic_extractor import LLMTopicExtractor
from sophia.domain.errors import TopicExtractionError
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
    lecture_downloads,
    self_explanations,
    student_flashcards,
    topic_lecture_links,
    topic_mappings,
    transcript_segments,
    transcriptions,
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
from sophia.services.hermes_setup import load_hermes_config
from sophia.services.idempotency import insert_or_fetch_row

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Row, Select
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.adapters.embedder import SentenceTransformerEmbedder
    from sophia.adapters.knowledge_store import ChromaKnowledgeStore
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

_MAX_TRANSCRIPT_CHARS = 12_000


def _create_topic_extractor(app: AppContainer) -> LLMTopicExtractor:
    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        raise TopicExtractionError("Hermes not configured — run: sophia hermes setup")
    return LLMTopicExtractor(config.llm)


# Module-level caches — one instance per CLI session, not per function call.
# The ~500 MB embedding model is expensive to reload; ChromaDB benefits from
# persistent client reuse as well.
_embedder_cache: SentenceTransformerEmbedder | None = None
_store_cache: ChromaKnowledgeStore | None = None


def _get_or_create_embedder(config: Any) -> SentenceTransformerEmbedder:
    """Return a cached embedder, creating it on first call."""
    from sophia.adapters.embedder import SentenceTransformerEmbedder

    global _embedder_cache
    if _embedder_cache is None:
        _embedder_cache = SentenceTransformerEmbedder(config.embeddings)
    return _embedder_cache


def _get_or_create_store(settings: Any) -> ChromaKnowledgeStore:
    """Return a cached knowledge store, creating it on first call."""
    from sophia.adapters.knowledge_store import ChromaKnowledgeStore

    global _store_cache
    if _store_cache is None:
        _store_cache = ChromaKnowledgeStore(settings.data_dir / "knowledge")
    return _store_cache


async def _get_episode_ids(session: AsyncSession, module_id: int) -> list[str]:
    """Fetch episode IDs for a module to scope ChromaDB searches."""
    return list(
        (
            await session.scalars(
                select(lecture_downloads.c.episode_id).where(
                    lecture_downloads.c.module_id == module_id,
                )
            )
        ).all()
    )


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


async def _get_series_title(session: AsyncSession, module_id: int) -> str:
    """Get the series title for a module to provide LLM context."""
    series_id = await session.scalar(
        select(lecture_downloads.c.series_id)
        .where(lecture_downloads.c.module_id == module_id)
        .limit(1)
    )
    return series_id or ""


async def _get_transcript_text(session: AsyncSession, module_id: int) -> str:
    """Get representative transcript text from a module's indexed lectures."""
    rows = list(
        (
            await session.scalars(
                select(transcript_segments.c.text)
                .join(
                    transcriptions,
                    transcriptions.c.episode_id == transcript_segments.c.episode_id,
                )
                .where(
                    transcriptions.c.module_id == module_id,
                    transcriptions.c.status == "completed",
                )
                .order_by(transcriptions.c.episode_id, transcript_segments.c.segment_index)
            )
        ).all()
    )
    if not rows:
        return ""

    # Concatenate segments until we hit the character budget
    parts: list[str] = []
    total = 0
    for text in rows:
        if total + len(text) > _MAX_TRANSCRIPT_CHARS:
            break
        parts.append(text)
        total += len(text)

    return " ".join(parts)


async def extract_topics_from_lectures(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    *,
    on_progress: Callable[[str], None] | None = None,
    force: bool = False,
) -> list[TopicMapping]:
    """Extract topics from indexed lecture transcripts for a module.

    When ``force=False`` (default) and topics already exist in the DB for this
    module, the LLM call is skipped and the cached topics are returned.  This
    prevents the pipeline and the ``study topics`` CLI command from produing
    mixed-language duplicates when both are run against the same module.

    Pass ``force=True`` (used by the full pipeline after fresh transcription)
    to delete existing topics and re-extract.

    1. Return cached topics if present (unless force=True)
    2. Load transcript segments from DB for the module
    3. Concatenate representative text (budgeted to _MAX_TRANSCRIPT_CHARS)
    4. Call LLM TopicExtractor to get topic labels
    5. Persist to topic_mappings table
    6. Return the extracted topics
    """
    course_id = module_id

    if not force:
        existing = await get_course_topics(session, course_id)
        if existing:
            log.info("topics_cached", module_id=module_id, count=len(existing))
            return existing

    if force:
        await session.execute(
            delete(topic_mappings).where(
                topic_mappings.c.course_id == course_id,
                topic_mappings.c.source == TopicSource.LECTURE.value,
            )
        )

    text = await _get_transcript_text(session, module_id)
    if not text:
        log.info("no_transcripts_for_topics", module_id=module_id)
        return []

    if on_progress:
        on_progress("Extracting topics from lecture transcripts…")

    extractor = _create_topic_extractor(app)

    series_title = await _get_series_title(session, module_id)
    topic_labels = await extractor.extract_topics(text, course_context=series_title)

    if not topic_labels:
        log.info("no_topics_extracted", module_id=module_id)
        return []

    # Persist with upsert (idempotent)
    mappings: list[TopicMapping] = []
    for label in topic_labels:
        statement = pg_insert(topic_mappings).values(
            topic=label,
            course_id=course_id,
            source=TopicSource.LECTURE.value,
            frequency=1,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    topic_mappings.c.topic,
                    topic_mappings.c.course_id,
                    topic_mappings.c.source,
                ],
                set_={"frequency": topic_mappings.c.frequency + 1},
            )
        )
        mappings.append(TopicMapping(topic=label, course_id=course_id, source=TopicSource.LECTURE))

    # Reconcile manual predictions against extracted topics
    from sophia.services.athena_reconciliation import reconcile_manual_topics

    result = await reconcile_manual_topics(session, course_id)
    if result.matched or result.unmatched_manual or result.new_moodle:
        log.info(
            "topics_reconciled",
            module_id=module_id,
            matched=len(result.matched),
            unmatched=len(result.unmatched_manual),
            new_moodle=len(result.new_moodle),
        )

    log.info("topics_extracted", module_id=module_id, count=len(mappings))
    return mappings


async def link_topics_to_lectures(
    app: AppContainer,
    session: AsyncSession,
    course_id: int,
    module_id: int,
    topics: list[str],
    *,
    on_progress: Callable[[str, int], None] | None = None,
) -> dict[str, list[tuple[KnowledgeChunk, float]]]:
    """Cross-reference topics with lecture chunks via semantic search.

    For each topic:
    1. Embed the topic text
    2. Search the KnowledgeStore scoped to this module's episode_ids
    3. Store links in topic_lecture_links table
    4. Return mapping of topic -> [(chunk, score), ...]
    """
    if not topics:
        return {}

    episode_ids = await _get_episode_ids(session, module_id)
    if not episode_ids:
        log.info("no_episodes_for_linking", module_id=module_id)
        return {}

    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        from sophia.domain.models import HermesConfig

        config = HermesConfig()
    embedder = _get_or_create_embedder(config)
    store = _get_or_create_store(app.settings)

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


async def get_lecture_context(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    topic: str,
    *,
    n_results: int = 5,
    with_provenance: bool = False,
    include_materials: bool = False,
    course_id: int | None = None,
) -> str:
    """Retrieve concatenated lecture transcript chunks relevant to a topic.

    Uses RAG: embed topic → search ChromaDB scoped to module's episodes.
    Returns empty string if no lecture data is available.

    When ``with_provenance=True`` each chunk is prefixed with
    ``[Title, MM:SS]`` so the reader knows its source and timestamp.

    When ``include_materials=True`` PDF material chunks are also searched
    and appended with ``[PDF: name, chunk N]`` provenance annotations.
    """
    episode_ids = await _get_episode_ids(session, module_id)
    if not episode_ids:
        return ""

    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        from sophia.domain.models import HermesConfig

        config = HermesConfig()
    embedder = _get_or_create_embedder(config)
    store = _get_or_create_store(app.settings)
    query_embedding = await asyncio.to_thread(embedder.embed_query, topic)
    search_results: list[tuple[KnowledgeChunk, float]] = await asyncio.to_thread(
        store.search, query_embedding, n_results=n_results, episode_ids=episode_ids
    )

    # Optionally search PDF material chunks
    pdf_results: list[tuple[KnowledgeChunk, float]] = []
    mat_name_map: dict[str, str] = {}
    if include_materials and course_id is not None:
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
        rows = (
            await session.execute(
                select(lecture_downloads.c.episode_id, lecture_downloads.c.title).where(
                    lecture_downloads.c.episode_id.in_(ep_ids),
                )
            )
        ).all()
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


async def generate_study_questions(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    topic: str,
    count: int = 3,
    difficulty: str = "explain",
) -> list[str]:
    """Generate practice questions for a topic, grounded in lecture content.

    Uses RAG: embed topic → search lecture chunks → feed to LLM as context.
    Falls back to generic questions if no lecture data or no LLM.
    """
    lecture_context = await get_lecture_context(app, session, module_id, topic)

    if not lecture_context:
        return [_FALLBACK_QUESTION.format(topic=topic)] * count

    extractor = _create_topic_extractor(app)
    questions: list[str] = []
    for _ in range(count):
        try:
            q = await extractor.generate_question(topic, lecture_context, difficulty=difficulty)
            if q and q not in questions:
                questions.append(q)
        except TopicExtractionError:
            log.warning("question_generation_failed", topic=topic)
            break

    while len(questions) < count:
        questions.append(_FALLBACK_QUESTION.format(topic=topic))

    return questions


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
