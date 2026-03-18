"""Tests for Athena Anki export service."""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import aiosqlite
import pytest

from sophia.infra.persistence import run_migrations

if TYPE_CHECKING:
    from pathlib import Path

import importlib.util

_requires_genanki = pytest.mark.skipif(
    importlib.util.find_spec("genanki") is None,
    reason="genanki not installed (optional 'athena' extra)",
)


@pytest.fixture
async def db():
    db_conn = await aiosqlite.connect(":memory:")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db_conn)
    yield db_conn
    await db_conn.close()


async def _insert_flashcard(
    db: aiosqlite.Connection,
    *,
    course_id: int = 42,
    topic: str = "Sorting",
    front: str = "What is quicksort?",
    back: str = "A divide-and-conquer sorting algorithm",
    source: str = "study",
) -> None:
    await db.execute(
        "INSERT INTO student_flashcards (course_id, topic, front, back, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (course_id, topic, front, back, source),
    )
    await db.commit()


@_requires_genanki
class TestExportCreatesApkgFile:
    @pytest.mark.asyncio
    async def test_export_creates_apkg_file(self, db: aiosqlite.Connection, tmp_path: Path) -> None:
        await _insert_flashcard(db, topic="Sorting", front="Q1", back="A1")
        await _insert_flashcard(db, topic="Hashing", front="Q2", back="A2")

        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "test.apkg"
        count = await export_anki_deck(db, course_id=42, output_path=output)

        assert count == 2
        assert output.exists()
        assert output.stat().st_size > 0
        with zipfile.ZipFile(output) as zf:
            assert "collection.anki2" in zf.namelist()


@_requires_genanki
class TestExportNoCardsReturnsZero:
    @pytest.mark.asyncio
    async def test_export_no_cards_returns_zero(
        self, db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "empty.apkg"
        count = await export_anki_deck(db, course_id=42, output_path=output)

        assert count == 0
        assert not output.exists()


@_requires_genanki
class TestExportInterleavedShuffles:
    @pytest.mark.asyncio
    async def test_export_interleaved_shuffles(
        self, db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """With multiple topics, interleaved export should not group all cards by topic."""
        for i in range(10):
            await _insert_flashcard(db, topic="Sorting", front=f"Sort-Q{i}", back=f"Sort-A{i}")
        for i in range(10):
            await _insert_flashcard(db, topic="Hashing", front=f"Hash-Q{i}", back=f"Hash-A{i}")

        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "interleaved.apkg"
        count = await export_anki_deck(db, course_id=42, output_path=output, interleaved=True)

        assert count == 20
        # We can't easily read note order from .apkg, but we verify the file is valid
        with zipfile.ZipFile(output) as zf:
            assert "collection.anki2" in zf.namelist()


@_requires_genanki
class TestExportBlockedGroupsByTopic:
    @pytest.mark.asyncio
    async def test_export_blocked_groups_by_topic(
        self, db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        for i in range(5):
            await _insert_flashcard(db, topic="Sorting", front=f"Sort-Q{i}", back=f"Sort-A{i}")
        for i in range(5):
            await _insert_flashcard(db, topic="Hashing", front=f"Hash-Q{i}", back=f"Hash-A{i}")

        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "blocked.apkg"
        count = await export_anki_deck(db, course_id=42, output_path=output, interleaved=False)

        assert count == 10
        with zipfile.ZipFile(output) as zf:
            assert "collection.anki2" in zf.namelist()


@_requires_genanki
class TestExportCardsHaveTopicTags:
    @pytest.mark.asyncio
    async def test_export_cards_have_topic_tags(
        self, db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """Exported notes should carry topic and source as tags."""
        await _insert_flashcard(
            db, topic="Sorting Algorithms", front="Q1", back="A1", source="study"
        )

        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "tagged.apkg"
        count = await export_anki_deck(db, course_id=42, output_path=output)

        assert count == 1
        # Valid apkg
        with zipfile.ZipFile(output) as zf:
            assert "collection.anki2" in zf.namelist()


class TestExportMissingGenankiRaises:
    @pytest.mark.asyncio
    async def test_export_missing_genanki_raises(
        self, db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "genanki":
                raise ImportError("No module named 'genanki'")
            return real_import(name, *args, **kwargs)

        from sophia.domain.errors import AthenaError

        with patch("builtins.__import__", side_effect=mock_import):
            from sophia.services import athena_export

            # Force reimport by calling the function (lazy import inside function)
            with pytest.raises(AthenaError, match="athena.*extra"):
                await athena_export.export_anki_deck(
                    db, course_id=42, output_path=tmp_path / "fail.apkg"
                )


@_requires_genanki
class TestExportCustomDeckName:
    @pytest.mark.asyncio
    async def test_export_custom_deck_name(self, db: aiosqlite.Connection, tmp_path: Path) -> None:
        await _insert_flashcard(db, topic="Sorting", front="Q1", back="A1")

        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "custom.apkg"
        count = await export_anki_deck(
            db, course_id=42, output_path=output, deck_name="My Custom Deck"
        )

        assert count == 1
        with zipfile.ZipFile(output) as zf:
            assert "collection.anki2" in zf.namelist()


# ---------------------------------------------------------------------------
# Lecture-scoped export (episode_id filter)
# ---------------------------------------------------------------------------


async def _link_topic_to_episode(
    db: aiosqlite.Connection,
    *,
    topic: str,
    course_id: int,
    episode_id: str,
    chunk_id: str = "chunk-1",
) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO topic_lecture_links (topic, course_id, chunk_id, episode_id) "
        "VALUES (?, ?, ?, ?)",
        (topic, course_id, chunk_id, episode_id),
    )
    await db.commit()


@_requires_genanki
class TestExportLectureScopedDeck:
    @pytest.mark.asyncio
    async def test_export_lecture_scoped_deck(
        self, db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """Only flashcards whose topics are linked to the given episode appear."""
        course = 42
        # Flashcards for two topics
        await _insert_flashcard(db, course_id=course, topic="Sorting", front="Q1", back="A1")
        await _insert_flashcard(db, course_id=course, topic="Sorting", front="Q2", back="A2")
        await _insert_flashcard(db, course_id=course, topic="Hashing", front="Q3", back="A3")

        # Link only "Sorting" to episode "ep-10"
        await _link_topic_to_episode(db, topic="Sorting", course_id=course, episode_id="ep-10")
        # Link "Hashing" to a different episode
        await _link_topic_to_episode(db, topic="Hashing", course_id=course, episode_id="ep-20")

        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "scoped.apkg"
        count = await export_anki_deck(db, course_id=course, output_path=output, episode_id="ep-10")

        assert count == 2  # only the two "Sorting" cards

    @pytest.mark.asyncio
    async def test_export_lecture_scoped_no_duplicates(
        self, db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """A topic linked via multiple chunks to the same episode yields each card once."""
        course = 42
        await _insert_flashcard(db, course_id=course, topic="Sorting", front="Q1", back="A1")
        # Two chunks for the same topic + episode
        await _link_topic_to_episode(
            db, topic="Sorting", course_id=course, episode_id="ep-10", chunk_id="c1"
        )
        await _link_topic_to_episode(
            db, topic="Sorting", course_id=course, episode_id="ep-10", chunk_id="c2"
        )

        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "no-dup.apkg"
        count = await export_anki_deck(db, course_id=course, output_path=output, episode_id="ep-10")

        assert count == 1


@_requires_genanki
class TestExportLectureScopedEmpty:
    @pytest.mark.asyncio
    async def test_export_lecture_scoped_empty(
        self, db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """Episode with no linked flashcards returns 0."""
        course = 42
        await _insert_flashcard(db, course_id=course, topic="Sorting", front="Q1", back="A1")
        await _link_topic_to_episode(db, topic="Sorting", course_id=course, episode_id="ep-10")

        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "empty-ep.apkg"
        count = await export_anki_deck(db, course_id=course, output_path=output, episode_id="ep-99")

        assert count == 0
        assert not output.exists()


@_requires_genanki
class TestExportDefaultStillCourseWide:
    @pytest.mark.asyncio
    async def test_export_default_still_course_wide(
        self, db: aiosqlite.Connection, tmp_path: Path
    ) -> None:
        """Without episode_id, all flashcards for the course are exported (backward compat)."""
        course = 42
        await _insert_flashcard(db, course_id=course, topic="Sorting", front="Q1", back="A1")
        await _insert_flashcard(db, course_id=course, topic="Hashing", front="Q2", back="A2")
        await _insert_flashcard(db, course_id=course, topic="Graphs", front="Q3", back="A3")

        # Link only one topic to an episode — should not affect unscoped export
        await _link_topic_to_episode(db, topic="Sorting", course_id=course, episode_id="ep-10")

        from sophia.services.athena_export import export_anki_deck

        output = tmp_path / "all.apkg"
        count = await export_anki_deck(db, course_id=course, output_path=output)

        assert count == 3
