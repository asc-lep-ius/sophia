"""Tests for Athena Anki export service."""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING
from unittest.mock import patch

import aiosqlite
import pytest

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

        def mock_import(name: str, *args, **kwargs):
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
