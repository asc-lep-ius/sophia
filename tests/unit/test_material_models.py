"""Tests for course material schema (migration 015) and domain models."""

from __future__ import annotations

import aiosqlite
import pytest

from sophia.domain.models import CourseMaterial, KnowledgeChunk, MaterialSource
from sophia.infra.persistence import run_migrations


@pytest.fixture
async def db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(conn)
    yield conn
    await conn.close()


# --- Schema tests ---


class TestMigration015:
    async def test_course_materials_table_exists(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='course_materials'"
        )
        row = await cursor.fetchone()
        assert row is not None

    async def test_course_materials_columns(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA table_info(course_materials)")
        columns = {row[1] for row in await cursor.fetchall()}
        expected = {
            "id",
            "course_id",
            "module_id",
            "name",
            "url",
            "mimetype",
            "file_size_bytes",
            "pdf_text",
            "chunk_count",
            "status",
            "error",
            "created_at",
        }
        assert expected <= columns

    async def test_lecture_number_column_exists(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA table_info(lecture_downloads)")
        columns = {row[1]: row[2] for row in await cursor.fetchall()}
        assert "lecture_number" in columns
        assert columns["lecture_number"] == "INTEGER"

    async def test_lecture_number_is_nullable(self, db: aiosqlite.Connection) -> None:
        """lecture_number should be NULL by default for existing rows."""
        await db.execute(
            "INSERT INTO lecture_downloads"
            " (episode_id, module_id, series_id, title, track_url, track_mimetype, status)"
            " VALUES ('ep1', 1, 's1', 'Lecture 1', 'https://x.com/a.mp3', 'audio/mpeg', 'queued')"
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT lecture_number FROM lecture_downloads WHERE episode_id='ep1'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] is None

    async def test_unique_constraint_on_course_materials_url(
        self, db: aiosqlite.Connection
    ) -> None:
        await db.execute(
            "INSERT INTO course_materials (course_id, module_id, name, url)"
            " VALUES (1, 10, 'Slides Week 1', 'https://example.com/slides.pdf')"
        )
        await db.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO course_materials (course_id, module_id, name, url)"
                " VALUES (1, 11, 'Duplicate URL', 'https://example.com/slides.pdf')"
            )

    async def test_unique_constraint_allows_different_courses(
        self,
        db: aiosqlite.Connection,
    ) -> None:
        """Same URL in different courses is allowed."""
        await db.execute(
            "INSERT INTO course_materials (course_id, module_id, name, url)"
            " VALUES (1, 10, 'Slides', 'https://example.com/slides.pdf')"
        )
        await db.execute(
            "INSERT INTO course_materials (course_id, module_id, name, url)"
            " VALUES (2, 20, 'Slides', 'https://example.com/slides.pdf')"
        )
        await db.commit()


# --- Domain model tests ---


class TestMaterialSource:
    def test_lecture_value(self) -> None:
        assert MaterialSource.LECTURE == "lecture"

    def test_pdf_value(self) -> None:
        assert MaterialSource.PDF == "pdf"

    def test_is_str(self) -> None:
        assert isinstance(MaterialSource.LECTURE, str)


class TestCourseMaterial:
    def test_create_with_required_fields(self) -> None:
        mat = CourseMaterial(id=1, course_id=100, module_id=200, name="Slides Week 1")
        assert mat.id == 1
        assert mat.course_id == 100
        assert mat.module_id == 200
        assert mat.name == "Slides Week 1"
        assert mat.status == "pending"
        assert mat.chunk_count == 0

    def test_create_with_all_fields(self) -> None:
        mat = CourseMaterial(
            id=1,
            course_id=100,
            module_id=200,
            name="Slides",
            url="https://example.com/slides.pdf",
            mimetype="application/pdf",
            file_size_bytes=102400,
            status="completed",
            chunk_count=15,
            created_at="2026-01-15 10:00:00",
        )
        assert mat.url == "https://example.com/slides.pdf"
        assert mat.mimetype == "application/pdf"
        assert mat.file_size_bytes == 102400
        assert mat.status == "completed"
        assert mat.chunk_count == 15

    def test_frozen(self) -> None:
        mat = CourseMaterial(id=1, course_id=100, module_id=200, name="Slides")
        with pytest.raises(Exception):  # noqa: B017
            mat.name = "Changed"  # type: ignore[misc]


class TestKnowledgeChunkSource:
    def test_default_source_is_lecture(self) -> None:
        chunk = KnowledgeChunk(
            chunk_id="c1",
            episode_id="ep1",
            chunk_index=0,
            text="Hello",
            start_time=0.0,
            end_time=5.0,
        )
        assert chunk.source == "lecture"

    def test_source_pdf(self) -> None:
        chunk = KnowledgeChunk(
            chunk_id="c2",
            episode_id="ep2",
            chunk_index=0,
            text="From PDF",
            start_time=0.0,
            end_time=0.0,
            source="pdf",
        )
        assert chunk.source == "pdf"
