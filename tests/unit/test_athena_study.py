"""Tests for the Athena study service — topic extraction, linking, study sessions, flashcards."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from sophia.domain.models import (
    FlashcardSource,
    KnowledgeChunk,
    StudentFlashcard,
    StudySession,
    TopicSource,
)
from sophia.infra.persistence import run_migrations

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def db():
    db_conn = await aiosqlite.connect(":memory:")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db_conn)
    yield db_conn
    await db_conn.close()


@pytest.fixture
def hermes_config(tmp_path: Path) -> None:
    """Write a minimal hermes.toml so load_hermes_config finds it."""
    config_file = tmp_path / "config" / "hermes.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        "[whisper]\n"
        'model = "large-v3"\n'
        'device = "cpu"\n'
        'compute_type = "float32"\n'
        "\n"
        "[llm]\n"
        'provider = "github"\n'
        'model = "openai/gpt-4o"\n'
        'api_key_env = "GITHUB_TOKEN"\n'
        "\n"
        "[embeddings]\n"
        'provider = "local"\n'
        'model = "intfloat/multilingual-e5-large"\n'
    )


@pytest.fixture
def app(db: aiosqlite.Connection, tmp_path: Path, hermes_config: None) -> MagicMock:
    mock = MagicMock()
    mock.db = db
    mock.settings.config_dir = tmp_path / "config"
    mock.settings.cache_dir = tmp_path / "cache"
    mock.settings.data_dir = tmp_path / "data"
    return mock


async def _insert_download(
    db: aiosqlite.Connection,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
    title: str = "Lecture 1",
) -> None:
    await db.execute(
        """INSERT INTO lecture_downloads
           (episode_id, module_id, series_id, title, track_url, track_mimetype,
            file_path, status)
           VALUES (?, ?, 'series-1', ?, 'https://example.com/a.mp3', 'audio/mpeg',
                   '/tmp/audio.mp3', 'completed')""",
        (episode_id, module_id, title),
    )
    await db.commit()


async def _insert_transcription(
    db: aiosqlite.Connection,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
) -> None:
    await db.execute(
        "INSERT INTO transcriptions (episode_id, module_id, segment_count, status) "
        "VALUES (?, ?, 5, 'completed')",
        (episode_id, module_id),
    )
    await db.commit()


async def _insert_segments(
    db: aiosqlite.Connection,
    *,
    episode_id: str = "ep-001",
    count: int = 5,
) -> None:
    for i in range(count):
        await db.execute(
            "INSERT INTO transcript_segments "
            "(episode_id, segment_index, start_time, end_time, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (episode_id, i, float(i * 5), float((i + 1) * 5), f"Segment about topic {i}"),
        )
    await db.commit()


# ---------------------------------------------------------------------------
# get_course_topics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_course_topics_empty(app: MagicMock) -> None:
    from sophia.services.athena_study import get_course_topics

    result = await get_course_topics(app, course_id=99)
    assert result == []


@pytest.mark.asyncio
async def test_get_course_topics_returns_persisted(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    from sophia.services.athena_study import get_course_topics

    await db.execute(
        "INSERT INTO topic_mappings (topic, course_id, source, frequency) VALUES (?, ?, ?, ?)",
        ("Linear Algebra", 42, "lecture", 2),
    )
    await db.execute(
        "INSERT INTO topic_mappings (topic, course_id, source, frequency) VALUES (?, ?, ?, ?)",
        ("Calculus", 42, "lecture", 1),
    )
    await db.commit()

    result = await get_course_topics(app, course_id=42)
    assert len(result) == 2
    assert result[0].topic == "Linear Algebra"
    assert result[0].frequency == 2


# ---------------------------------------------------------------------------
# extract_topics_from_lectures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_topics_no_transcripts(app: MagicMock) -> None:
    from sophia.services.athena_study import extract_topics_from_lectures

    result = await extract_topics_from_lectures(app, module_id=42)
    assert result == []


@pytest.mark.asyncio
async def test_extract_topics_from_lectures_success(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    from sophia.services.athena_study import extract_topics_from_lectures

    await _insert_download(db, episode_id="ep-001", module_id=42)
    await _insert_transcription(db, episode_id="ep-001", module_id=42)
    await _insert_segments(db, episode_id="ep-001", count=5)

    mock_extractor = AsyncMock()
    mock_extractor.extract_topics = AsyncMock(return_value=["Linear Algebra", "Matrix Operations"])

    with patch(
        "sophia.services.athena_study._create_topic_extractor",
        return_value=mock_extractor,
    ):
        result = await extract_topics_from_lectures(app, module_id=42)

    assert len(result) == 2
    assert result[0].topic == "Linear Algebra"
    assert result[0].source == TopicSource.LECTURE

    # Verify persisted to DB
    from sophia.services.athena_study import get_course_topics

    # Get course_id from the lecture_downloads
    cursor = await db.execute(
        "SELECT DISTINCT module_id FROM lecture_downloads WHERE module_id = 42"
    )
    row = await cursor.fetchone()
    assert row is not None

    # Topics should be in the DB now — use course_id from result
    topics = await get_course_topics(app, course_id=result[0].course_id)
    assert len(topics) == 2


@pytest.mark.asyncio
async def test_extract_topics_idempotent(app: MagicMock, db: aiosqlite.Connection) -> None:
    """Re-running extraction upserts but doesn't duplicate topics."""
    from sophia.services.athena_study import extract_topics_from_lectures

    await _insert_download(db, episode_id="ep-001", module_id=42)
    await _insert_transcription(db, episode_id="ep-001", module_id=42)
    await _insert_segments(db, episode_id="ep-001", count=3)

    mock_extractor = AsyncMock()
    mock_extractor.extract_topics = AsyncMock(return_value=["Sorting"])

    with patch(
        "sophia.services.athena_study._create_topic_extractor",
        return_value=mock_extractor,
    ):
        await extract_topics_from_lectures(app, module_id=42)
        # Run again — should upsert, not duplicate
        await extract_topics_from_lectures(app, module_id=42)

    cursor = await db.execute("SELECT COUNT(*) FROM topic_mappings WHERE topic = 'Sorting'")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1


@pytest.mark.asyncio
async def test_extract_topics_skips_llm_when_cached(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    """With force=False (default), a pre-existing topic set skips the LLM call.

    This is the regression guard for the mixed-language duplicate bug: if
    ``lectures process`` already stored German topics, a subsequent
    ``study topics`` run must NOT call the LLM and must NOT insert English
    duplicates.
    """
    from sophia.services.athena_study import extract_topics_from_lectures

    # Pre-seed German topics (as lectures process would have done)
    await db.execute(
        "INSERT INTO topic_mappings (topic, course_id, source, frequency) VALUES (?, ?, ?, ?)",
        ("Mathematische Aussagen", 42, "lecture", 1),
    )
    await db.execute(
        "INSERT INTO topic_mappings (topic, course_id, source, frequency) VALUES (?, ?, ?, ?)",
        ("Direkter Beweis", 42, "lecture", 1),
    )
    await db.commit()

    mock_create_extractor = MagicMock()

    with patch(
        "sophia.services.athena_study._create_topic_extractor",
        mock_create_extractor,
    ):
        result = await extract_topics_from_lectures(app, module_id=42)

    # LLM extractor must never be instantiated
    mock_create_extractor.assert_not_called()
    # Existing German topics are returned as-is
    assert len(result) == 2
    assert {r.topic for r in result} == {"Mathematische Aussagen", "Direkter Beweis"}


@pytest.mark.asyncio
async def test_extract_topics_force_replaces_cached(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    """With force=True the existing topics are deleted and the LLM is called."""
    from sophia.services.athena_study import extract_topics_from_lectures

    await _insert_download(db, episode_id="ep-001", module_id=42)
    await _insert_transcription(db, episode_id="ep-001", module_id=42)
    await _insert_segments(db, episode_id="ep-001", count=3)

    # Pre-seed stale topics
    await db.execute(
        "INSERT INTO topic_mappings (topic, course_id, source, frequency) VALUES (?, ?, ?, ?)",
        ("Old Topic", 42, "lecture", 1),
    )
    await db.commit()

    mock_extractor = AsyncMock()
    mock_extractor.extract_topics = AsyncMock(return_value=["Neues Thema"])

    with patch(
        "sophia.services.athena_study._create_topic_extractor",
        return_value=mock_extractor,
    ):
        result = await extract_topics_from_lectures(app, module_id=42, force=True)

    assert len(result) == 1
    assert result[0].topic == "Neues Thema"
    # Old stale topic must be gone
    cursor = await db.execute("SELECT COUNT(*) FROM topic_mappings WHERE topic = 'Old Topic'")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0


# ---------------------------------------------------------------------------
# link_topics_to_lectures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_topics_empty_topics(app: MagicMock) -> None:
    from sophia.services.athena_study import link_topics_to_lectures

    result = await link_topics_to_lectures(app, course_id=42, module_id=42, topics=[])
    assert result == {}


@pytest.mark.asyncio
async def test_link_topics_to_lectures_success(app: MagicMock, db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import link_topics_to_lectures

    await _insert_download(db, episode_id="ep-001", module_id=42)

    mock_chunk = KnowledgeChunk(
        chunk_id="ep-001_0",
        episode_id="ep-001",
        chunk_index=0,
        text="Introduction to sorting algorithms",
        start_time=0.0,
        end_time=15.0,
    )

    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1, 0.2, 0.3]

    mock_store = MagicMock()
    mock_store.search.return_value = [(mock_chunk, 0.92)]

    with (
        patch(
            "sophia.services.athena_study._get_or_create_embedder",
            return_value=mock_embedder,
        ),
        patch(
            "sophia.services.athena_study._get_or_create_store",
            return_value=mock_store,
        ),
        patch(
            "sophia.services.athena_study.asyncio.to_thread",
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),  # pyright: ignore[reportUnknownLambdaType]
        ),
    ):
        result = await link_topics_to_lectures(app, course_id=42, module_id=42, topics=["Sorting"])

    assert "Sorting" in result
    assert len(result["Sorting"]) == 1
    assert result["Sorting"][0][1] == pytest.approx(0.92)  # pyright: ignore[reportUnknownMemberType]

    # Verify persisted to DB
    cursor = await db.execute(
        "SELECT topic, chunk_id, score FROM topic_lecture_links WHERE course_id = 42"
    )
    rows = list(await cursor.fetchall())
    assert len(rows) == 1
    assert rows[0][0] == "Sorting"
    assert rows[0][1] == "ep-001_0"


# ---------------------------------------------------------------------------
# StudySession model
# ---------------------------------------------------------------------------


class TestStudySessionModel:
    """Tests for the StudySession domain model."""

    def test_improvement_both_scores(self) -> None:
        s = StudySession(course_id=1, topic="X", pre_test_score=0.33, post_test_score=0.67)
        assert s.improvement == pytest.approx(0.34)  # pyright: ignore[reportUnknownMemberType]

    def test_improvement_none_when_missing_pre(self) -> None:
        s = StudySession(course_id=1, topic="X", post_test_score=0.67)
        assert s.improvement is None

    def test_improvement_none_when_missing_post(self) -> None:
        s = StudySession(course_id=1, topic="X", pre_test_score=0.33)
        assert s.improvement is None

    def test_improvement_negative_means_worse(self) -> None:
        s = StudySession(course_id=1, topic="X", pre_test_score=1.0, post_test_score=0.33)
        assert s.improvement is not None
        assert s.improvement < 0

    def test_defaults(self) -> None:
        s = StudySession(course_id=1, topic="X")
        assert s.id == 0
        assert s.pre_test_score is None
        assert s.post_test_score is None
        assert s.completed_at is None


# ---------------------------------------------------------------------------
# StudentFlashcard model
# ---------------------------------------------------------------------------


class TestStudentFlashcardModel:
    """Tests for the StudentFlashcard domain model."""

    def test_create_with_defaults(self) -> None:
        f = StudentFlashcard(course_id=1, topic="X", front="Q?", back="A.")
        assert f.source == FlashcardSource.STUDY
        assert f.id == 0

    def test_create_with_source(self) -> None:
        f = StudentFlashcard(
            course_id=1, topic="X", front="Q?", back="A.", source=FlashcardSource.LECTURE
        )
        assert f.source == FlashcardSource.LECTURE


# ---------------------------------------------------------------------------
# start_study_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_study_session(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import start_study_session

    session = await start_study_session(db, course_id=42, topic="Sorting")
    assert session.course_id == 42
    assert session.topic == "Sorting"
    assert session.id > 0
    assert session.started_at != ""
    assert session.pre_test_score is None
    assert session.completed_at is None


@pytest.mark.asyncio
async def test_start_study_session_persists(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import start_study_session

    session = await start_study_session(db, course_id=42, topic="Sorting")
    cursor = await db.execute("SELECT id, topic FROM study_sessions WHERE id = ?", (session.id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[1] == "Sorting"


# ---------------------------------------------------------------------------
# complete_study_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_study_session(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import complete_study_session, start_study_session

    session = await start_study_session(db, course_id=42, topic="Sorting")
    await complete_study_session(db, session.id, pre_test_score=0.33, post_test_score=0.67)

    cursor = await db.execute(
        "SELECT pre_test_score, post_test_score, completed_at FROM study_sessions WHERE id = ?",
        (session.id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.33)  # pyright: ignore[reportUnknownMemberType]
    assert row[1] == pytest.approx(0.67)  # pyright: ignore[reportUnknownMemberType]
    assert row[2] is not None  # completed_at set


# ---------------------------------------------------------------------------
# get_study_sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_study_sessions_empty(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import get_study_sessions

    result = await get_study_sessions(db, course_id=99)
    assert result == []


@pytest.mark.asyncio
async def test_get_study_sessions_all(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import get_study_sessions, start_study_session

    await start_study_session(db, course_id=42, topic="Sorting")
    await start_study_session(db, course_id=42, topic="Graphs")

    result = await get_study_sessions(db, course_id=42)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_study_sessions_by_topic(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import get_study_sessions, start_study_session

    await start_study_session(db, course_id=42, topic="Sorting")
    await start_study_session(db, course_id=42, topic="Graphs")

    result = await get_study_sessions(db, course_id=42, topic="Sorting")
    assert len(result) == 1
    assert result[0].topic == "Sorting"


# ---------------------------------------------------------------------------
# save_flashcard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_flashcard(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import save_flashcard

    card = await save_flashcard(
        db,
        course_id=42,
        topic="Sorting",
        front="What is quicksort?",
        back="A divide-and-conquer algorithm",
    )
    assert card.id > 0
    assert card.front == "What is quicksort?"
    assert card.source == FlashcardSource.STUDY


@pytest.mark.asyncio
async def test_save_flashcard_with_source(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import save_flashcard

    card = await save_flashcard(
        db, course_id=42, topic="Sorting", front="Q?", back="A.", source="lecture"
    )
    assert card.source == FlashcardSource.LECTURE


@pytest.mark.asyncio
async def test_save_flashcard_persists(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import save_flashcard

    card = await save_flashcard(db, course_id=42, topic="Sorting", front="Q?", back="A.")
    cursor = await db.execute("SELECT front, back FROM student_flashcards WHERE id = ?", (card.id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "Q?"


# ---------------------------------------------------------------------------
# get_flashcards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_flashcards_empty(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import get_flashcards

    result = await get_flashcards(db, course_id=99)
    assert result == []


@pytest.mark.asyncio
async def test_get_flashcards_all(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import get_flashcards, save_flashcard

    await save_flashcard(db, course_id=42, topic="Sorting", front="Q1?", back="A1")
    await save_flashcard(db, course_id=42, topic="Graphs", front="Q2?", back="A2")

    result = await get_flashcards(db, course_id=42)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_flashcards_by_topic(db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import get_flashcards, save_flashcard

    await save_flashcard(db, course_id=42, topic="Sorting", front="Q1?", back="A1")
    await save_flashcard(db, course_id=42, topic="Graphs", front="Q2?", back="A2")

    result = await get_flashcards(db, course_id=42, topic="Sorting")
    assert len(result) == 1
    assert result[0].topic == "Sorting"


# ---------------------------------------------------------------------------
# generate_study_questions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_study_questions_with_llm(app: MagicMock, db: aiosqlite.Connection) -> None:
    """LLM generates questions grounded in lecture context."""
    from sophia.services.athena_study import generate_study_questions

    await _insert_download(db, episode_id="ep-001", module_id=42)

    mock_chunk = KnowledgeChunk(
        chunk_id="ep-001_0",
        episode_id="ep-001",
        chunk_index=0,
        text="Sorting: quicksort partitions an array around a pivot.",
        start_time=0.0,
        end_time=15.0,
    )
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1, 0.2]

    mock_store = MagicMock()
    mock_store.search.return_value = [(mock_chunk, 0.9)]

    mock_extractor = AsyncMock()
    mock_extractor.generate_question = AsyncMock(
        side_effect=["Q about pivots?", "Q about partitioning?", "Q about complexity?"]
    )

    with (
        patch("sophia.services.athena_study._get_or_create_embedder", return_value=mock_embedder),
        patch("sophia.services.athena_study._get_or_create_store", return_value=mock_store),
        patch(
            "sophia.services.athena_study._create_topic_extractor",
            return_value=mock_extractor,
        ),
        patch(
            "sophia.services.athena_study.asyncio.to_thread",
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),  # pyright: ignore[reportUnknownLambdaType]
        ),
    ):
        questions = await generate_study_questions(app, module_id=42, topic="Sorting", count=3)

    assert len(questions) == 3
    assert "Q about pivots?" in questions
    # Verify lecture context was passed to LLM
    call_args = mock_extractor.generate_question.call_args_list
    assert "quicksort" in call_args[0].args[1]


@pytest.mark.asyncio
async def test_generate_study_questions_fallback_no_lectures(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    """Falls back to generic questions when no lecture data available."""
    from sophia.services.athena_study import generate_study_questions

    # No downloads inserted → no episode_ids → fallback
    questions = await generate_study_questions(app, module_id=99, topic="Sorting", count=3)

    assert len(questions) == 3
    assert all("Sorting" in q for q in questions)


@pytest.mark.asyncio
async def test_generate_study_questions_llm_partial_failure(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    """Pads with fallback when LLM produces fewer questions than requested."""
    from sophia.services.athena_study import generate_study_questions

    await _insert_download(db, episode_id="ep-001", module_id=42)

    mock_chunk = KnowledgeChunk(
        chunk_id="ep-001_0",
        episode_id="ep-001",
        chunk_index=0,
        text="Sorting algorithms",
        start_time=0.0,
        end_time=15.0,
    )
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1]

    mock_store = MagicMock()
    mock_store.search.return_value = [(mock_chunk, 0.9)]

    mock_extractor = AsyncMock()
    from sophia.domain.errors import TopicExtractionError

    mock_extractor.generate_question = AsyncMock(
        side_effect=["One question?", TopicExtractionError("fail")]
    )

    with (
        patch("sophia.services.athena_study._get_or_create_embedder", return_value=mock_embedder),
        patch("sophia.services.athena_study._get_or_create_store", return_value=mock_store),
        patch(
            "sophia.services.athena_study._create_topic_extractor",
            return_value=mock_extractor,
        ),
        patch(
            "sophia.services.athena_study.asyncio.to_thread",
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),  # pyright: ignore[reportUnknownLambdaType]
        ),
    ):
        questions = await generate_study_questions(app, module_id=42, topic="Sorting", count=3)

    assert len(questions) == 3
    assert questions[0] == "One question?"
    # Remaining should be fallback
    assert "Sorting" in questions[1]


# ---------------------------------------------------------------------------
# Card reviews
# ---------------------------------------------------------------------------


class TestCardReview:
    """Card review service functions."""

    @pytest.mark.asyncio
    async def test_save_review_attempt(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import save_flashcard, save_review_attempt

        card = await save_flashcard(db, course_id=42, topic="Sorting", front="Q?", back="A.")
        attempt = await save_review_attempt(db, flashcard_id=card.id, success=True)

        assert attempt.id > 0
        assert attempt.flashcard_id == card.id
        assert attempt.success is True
        assert attempt.reviewed_at != ""

    @pytest.mark.asyncio
    async def test_get_review_stats_no_reviews(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import get_review_stats

        stats = await get_review_stats(db, course_id=99)
        assert stats["total_reviews"] == 0
        assert stats["success_count"] == 0
        assert stats["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_get_review_stats_with_reviews(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import (
            get_review_stats,
            save_flashcard,
            save_review_attempt,
        )

        c1 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q1", back="A1")
        c2 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q2", back="A2")
        await save_review_attempt(db, flashcard_id=c1.id, success=True)
        await save_review_attempt(db, flashcard_id=c2.id, success=False)
        await save_review_attempt(db, flashcard_id=c1.id, success=True)

        stats = await get_review_stats(db, course_id=42, topic="Sorting")
        assert stats["total_reviews"] == 3
        assert stats["success_count"] == 2
        assert stats["success_rate"] == pytest.approx(2 / 3)  # pyright: ignore[reportUnknownMemberType]

    @pytest.mark.asyncio
    async def test_get_review_stats_per_topic(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import (
            get_review_stats,
            save_flashcard,
            save_review_attempt,
        )

        c1 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q1", back="A1")
        c2 = await save_flashcard(db, course_id=42, topic="Graphs", front="Q2", back="A2")
        await save_review_attempt(db, flashcard_id=c1.id, success=True)
        await save_review_attempt(db, flashcard_id=c2.id, success=False)

        stats = await get_review_stats(db, course_id=42, topic="Sorting")
        assert stats["total_reviews"] == 1
        assert stats["success_count"] == 1

    @pytest.mark.asyncio
    async def test_get_due_cards_unreviewed_first(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import (
            get_due_cards,
            save_flashcard,
            save_review_attempt,
        )

        c1 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q1", back="A1")
        c2 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q2", back="A2")
        # Review c1 but not c2
        await save_review_attempt(db, flashcard_id=c1.id, success=True)

        due = await get_due_cards(db, course_id=42)
        assert len(due) == 2
        # Unreviewed card (c2) should come first
        assert due[0].id == c2.id

    @pytest.mark.asyncio
    async def test_get_due_cards_with_topic_filter(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import get_due_cards, save_flashcard

        await save_flashcard(db, course_id=42, topic="Sorting", front="Q1", back="A1")
        await save_flashcard(db, course_id=42, topic="Graphs", front="Q2", back="A2")

        due = await get_due_cards(db, course_id=42, topic="Graphs")
        assert len(due) == 1
        assert due[0].topic == "Graphs"

    @pytest.mark.asyncio
    async def test_get_due_cards_respects_limit(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import get_due_cards, save_flashcard

        for i in range(5):
            await save_flashcard(db, course_id=42, topic="Sorting", front=f"Q{i}", back=f"A{i}")

        due = await get_due_cards(db, course_id=42, limit=3)
        assert len(due) == 3

    @pytest.mark.asyncio
    async def test_update_topic_calibration(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import (
            save_flashcard,
            save_review_attempt,
            update_topic_calibration,
        )

        # Insert a confidence rating for the topic
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted, rated_at) "
            "VALUES (?, ?, ?, ?)",
            ("Sorting", 42, 0.75, "2026-01-01T00:00:00"),
        )
        await db.commit()

        # Create flashcards and review them
        c1 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q1", back="A1")
        c2 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q2", back="A2")
        await save_review_attempt(db, flashcard_id=c1.id, success=True)
        await save_review_attempt(db, flashcard_id=c2.id, success=False)

        # Calibrate — should update actual to 0.5 (1/2)
        await update_topic_calibration(db, course_id=42, topic="Sorting")

        cursor = await db.execute(
            "SELECT actual FROM confidence_ratings WHERE topic = ? AND course_id = ?",
            ("Sorting", 42),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == pytest.approx(0.5)  # pyright: ignore[reportUnknownMemberType]

    @pytest.mark.asyncio
    async def test_update_topic_calibration_no_reviews(self, db: aiosqlite.Connection) -> None:
        """No reviews → no calibration update (no crash)."""
        from sophia.services.athena_study import update_topic_calibration

        # Should not raise
        await update_topic_calibration(db, course_id=42, topic="Nonexistent")

    @pytest.mark.asyncio
    async def test_get_failed_review_cards_returns_wrong_answers(
        self, db: aiosqlite.Connection
    ) -> None:
        from sophia.services.athena_study import (
            get_failed_review_cards,
            save_flashcard,
            save_review_attempt,
        )

        c1 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q1", back="A1")
        c2 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q2", back="A2")
        await save_review_attempt(db, flashcard_id=c1.id, success=False)
        await save_review_attempt(db, flashcard_id=c2.id, success=True)

        failed = await get_failed_review_cards(db, course_id=42)
        assert len(failed) == 1
        assert failed[0].id == c1.id

    @pytest.mark.asyncio
    async def test_get_failed_review_cards_with_topic_filter(
        self, db: aiosqlite.Connection
    ) -> None:
        from sophia.services.athena_study import (
            get_failed_review_cards,
            save_flashcard,
            save_review_attempt,
        )

        c1 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q1", back="A1")
        c2 = await save_flashcard(db, course_id=42, topic="Hashing", front="Q2", back="A2")
        await save_review_attempt(db, flashcard_id=c1.id, success=False)
        await save_review_attempt(db, flashcard_id=c2.id, success=False)

        failed = await get_failed_review_cards(db, course_id=42, topic="Hashing")
        assert len(failed) == 1
        assert failed[0].topic == "Hashing"


# ---------------------------------------------------------------------------
# Self-explanation
# ---------------------------------------------------------------------------


class TestSelfExplanation:
    """Self-explanation service functions."""

    @pytest.mark.asyncio
    async def test_save_self_explanation(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import save_flashcard, save_self_explanation

        card = await save_flashcard(db, course_id=42, topic="Sorting", front="Q?", back="A.")
        exp = await save_self_explanation(
            db,
            flashcard_id=card.id,
            student_explanation="I confused quicksort with mergesort",
            scaffold_level=3,
        )

        assert exp.id > 0
        assert exp.flashcard_id == card.id
        assert exp.student_explanation == "I confused quicksort with mergesort"
        assert exp.scaffold_level == 3
        assert exp.created_at != ""

    @pytest.mark.asyncio
    async def test_get_self_explanations(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import (
            get_self_explanations,
            save_flashcard,
            save_self_explanation,
        )

        card = await save_flashcard(db, course_id=42, topic="Sorting", front="Q?", back="A.")
        await save_self_explanation(
            db,
            flashcard_id=card.id,
            student_explanation="First",
            scaffold_level=3,
        )
        await save_self_explanation(
            db,
            flashcard_id=card.id,
            student_explanation="Second",
            scaffold_level=1,
        )

        explanations = await get_self_explanations(db, flashcard_id=card.id)
        assert len(explanations) == 2
        # Reverse chronological — most recent first
        assert explanations[0].student_explanation == "Second"
        assert explanations[1].student_explanation == "First"

    @pytest.mark.asyncio
    async def test_get_explanation_count(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_study import (
            get_explanation_count,
            save_flashcard,
            save_self_explanation,
        )

        card1 = await save_flashcard(db, course_id=42, topic="Sorting", front="Q1", back="A1")
        card2 = await save_flashcard(db, course_id=42, topic="Graphs", front="Q2", back="A2")
        card_other = await save_flashcard(db, course_id=99, topic="Other", front="Q3", back="A3")

        await save_self_explanation(
            db,
            flashcard_id=card1.id,
            student_explanation="E1",
            scaffold_level=3,
        )
        await save_self_explanation(
            db,
            flashcard_id=card2.id,
            student_explanation="E2",
            scaffold_level=3,
        )
        await save_self_explanation(
            db,
            flashcard_id=card_other.id,
            student_explanation="E3",
            scaffold_level=3,
        )

        count = await get_explanation_count(db, course_id=42)
        assert count == 2

    def test_get_scaffold_level_full(self) -> None:
        from sophia.services.athena_study import get_scaffold_level

        assert get_scaffold_level(0) == 3
        assert get_scaffold_level(5) == 3
        assert get_scaffold_level(9) == 3

    def test_get_scaffold_level_medium(self) -> None:
        from sophia.services.athena_study import get_scaffold_level

        assert get_scaffold_level(10) == 1
        assert get_scaffold_level(15) == 1
        assert get_scaffold_level(19) == 1

    def test_get_scaffold_level_open(self) -> None:
        from sophia.services.athena_study import get_scaffold_level

        assert get_scaffold_level(20) == 0
        assert get_scaffold_level(50) == 0
        assert get_scaffold_level(100) == 0

    def test_get_scaffold_prompts_full(self) -> None:
        from sophia.services.athena_study import get_scaffold_prompts

        prompts = get_scaffold_prompts(3)
        assert len(prompts) == 3
        assert all(isinstance(p, str) for p in prompts)

    def test_get_scaffold_prompts_medium(self) -> None:
        from sophia.services.athena_study import get_scaffold_prompts

        prompts = get_scaffold_prompts(1)
        assert len(prompts) == 1

    def test_get_scaffold_prompts_open(self) -> None:
        from sophia.services.athena_study import get_scaffold_prompts

        prompts = get_scaffold_prompts(0)
        assert prompts == []


# ---------------------------------------------------------------------------
# get_lecture_context — dual-source (include_materials)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lecture_context_include_materials(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    """With include_materials=True, both lecture and PDF chunks appear with provenance.

    Uses distinct module_id (42) and course_id (999) to verify the correct ID
    reaches _search_material_chunks (which expects course_id, not module_id).
    """
    from sophia.services.athena_study import get_lecture_context

    await _insert_download(db, episode_id="ep-001", module_id=42)

    # Insert a course material — note course_id=999 differs from module_id=42
    await db.execute(
        "INSERT INTO course_materials (id, course_id, module_id, name, url, status, chunk_count) "
        "VALUES (?, ?, ?, ?, ?, 'completed', 5)",
        (10, 999, 42, "Algorithms.pdf", "https://example.com/algo.pdf"),
    )
    await db.commit()

    lecture_chunk = KnowledgeChunk(
        chunk_id="ep-001_0",
        episode_id="ep-001",
        chunk_index=0,
        text="Sorting is a fundamental operation",
        start_time=60.0,
        end_time=75.0,
        source="lecture",
    )
    pdf_chunk = KnowledgeChunk(
        chunk_id="mat-10_2",
        episode_id="mat-10",
        chunk_index=2,
        text="Quicksort runs in O(n log n) average case",
        start_time=0.0,
        end_time=0.0,
        source="pdf",
    )

    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1, 0.2, 0.3]

    mock_store = MagicMock()
    # First call: lecture search; second call: PDF search
    mock_store.search.side_effect = [
        [(lecture_chunk, 0.9)],
        [(pdf_chunk, 0.85)],
    ]

    with (
        patch(
            "sophia.services.athena_study._get_or_create_embedder",
            return_value=mock_embedder,
        ),
        patch(
            "sophia.services.athena_study._get_or_create_store",
            return_value=mock_store,
        ),
        patch(
            "sophia.services.athena_study.asyncio.to_thread",
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),  # pyright: ignore[reportUnknownLambdaType]
        ),
    ):
        result = await get_lecture_context(
            app,
            module_id=42,
            course_id=999,
            topic="Sorting",
            with_provenance=True,
            include_materials=True,
        )

    # Lecture chunk should appear with title provenance
    assert "Sorting is a fundamental operation" in result
    # PDF chunk should appear with [PDF: ...] provenance
    assert "[PDF: Algorithms.pdf" in result
    assert "Quicksort runs in O(n log n)" in result


@pytest.mark.asyncio
async def test_get_lecture_context_without_materials_flag(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    """Default call (include_materials=False) does NOT search PDF chunks."""
    from sophia.services.athena_study import get_lecture_context

    await _insert_download(db, episode_id="ep-001", module_id=42)

    lecture_chunk = KnowledgeChunk(
        chunk_id="ep-001_0",
        episode_id="ep-001",
        chunk_index=0,
        text="Binary trees are hierarchical",
        start_time=30.0,
        end_time=45.0,
        source="lecture",
    )

    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1, 0.2, 0.3]

    mock_store = MagicMock()
    mock_store.search.return_value = [(lecture_chunk, 0.88)]

    with (
        patch(
            "sophia.services.athena_study._get_or_create_embedder",
            return_value=mock_embedder,
        ),
        patch(
            "sophia.services.athena_study._get_or_create_store",
            return_value=mock_store,
        ),
        patch(
            "sophia.services.athena_study.asyncio.to_thread",
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),  # pyright: ignore[reportUnknownLambdaType]
        ),
    ):
        result = await get_lecture_context(
            app,
            module_id=42,
            topic="Trees",
        )

    assert "Binary trees are hierarchical" in result
    # store.search called exactly once (only lecture, no PDF query)
    assert mock_store.search.call_count == 1
