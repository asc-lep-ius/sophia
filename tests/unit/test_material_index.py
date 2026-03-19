"""Tests for the course material scraping, chunking, and indexing service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from sophia.domain.models import ContentInfo, ModuleInfo
from sophia.infra.persistence import run_migrations
from sophia.services.material_index import (
    _CHUNK_OVERLAP,
    _CHUNK_SIZE,
    chunk_pdf_text,
    index_materials,
    scrape_course_materials,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def db() -> AsyncGenerator[aiosqlite.Connection, None]:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(conn)
    yield conn
    await conn.close()


def _make_app(db: aiosqlite.Connection, *, moodle: MagicMock | None = None) -> MagicMock:
    """Build a minimal mock AppContainer with a real DB."""
    app = MagicMock()
    app.db = db
    app.settings.config_dir = "/tmp/sophia-test"
    app.settings.data_dir = MagicMock()
    app.settings.data_dir.__truediv__ = MagicMock(return_value="/tmp/sophia-test/knowledge")
    if moodle is not None:
        app.moodle = moodle
    return app


def _make_resource_module(
    module_id: int = 100,
    name: str = "Lecture Slides",
    url: str = "https://tuwel.tuwien.ac.at/mod/resource/view.php?id=100",
    mimetype: str = "application/pdf",
    fileurl: str = "https://tuwel.tuwien.ac.at/file.pdf",
    filesize: int = 1024,
) -> ModuleInfo:
    return ModuleInfo(
        id=module_id,
        name=name,
        modname="resource",
        url=url,
        contents=[
            ContentInfo(
                filename="slides.pdf",
                fileurl=fileurl,
                filesize=filesize,
                mimetype=mimetype,
            )
        ],
    )


# ---------------------------------------------------------------------------
# chunk_pdf_text
# ---------------------------------------------------------------------------


class TestChunkPdfText:
    def test_basic_chunking(self) -> None:
        text = "A" * 1200  # should produce multiple chunks
        chunks = chunk_pdf_text(text, material_id=42)

        assert len(chunks) >= 2
        for i, c in enumerate(chunks):
            assert c.chunk_id == f"mat-42_{i}"
            assert c.episode_id == "mat-42"
            assert c.chunk_index == i
            assert c.source == "pdf"
            assert c.start_time == 0.0
            assert c.end_time == 0.0

    def test_empty_text_returns_empty(self) -> None:
        assert chunk_pdf_text("", material_id=1) == []
        assert chunk_pdf_text("   \n  ", material_id=1) == []

    def test_short_text_returns_one_chunk(self) -> None:
        short = "Hello, this is a short PDF."
        chunks = chunk_pdf_text(short, material_id=7)

        assert len(chunks) == 1
        assert chunks[0].text == short
        assert chunks[0].source == "pdf"

    def test_overlap_between_adjacent_chunks(self) -> None:
        text = "X" * (_CHUNK_SIZE + _CHUNK_OVERLAP + 100)
        chunks = chunk_pdf_text(text, material_id=5)

        assert len(chunks) >= 2
        # The end of chunk 0 should overlap with the start of chunk 1
        end_of_first = chunks[0].text[-_CHUNK_OVERLAP:]
        start_of_second = chunks[1].text[:_CHUNK_OVERLAP]
        assert end_of_first == start_of_second

    def test_paragraph_boundary_preference(self) -> None:
        # Build text with a paragraph break near a chunk boundary
        para1 = "A" * (_CHUNK_SIZE - 30)
        para2 = "B" * 200
        text = para1 + "\n\n" + para2
        chunks = chunk_pdf_text(text, material_id=3)

        assert len(chunks) >= 2
        # First chunk should end at or before paragraph boundary
        assert chunks[0].text.endswith("A") or chunks[0].text.endswith("\n")


# ---------------------------------------------------------------------------
# scrape_course_materials (async, needs DB)
# ---------------------------------------------------------------------------


class TestScrapCourseMaterials:
    @pytest.mark.asyncio
    async def test_scrape_inserts_materials(self, db: aiosqlite.Connection) -> None:
        moodle = MagicMock()
        moodle.get_course_resources = AsyncMock(return_value=[_make_resource_module(module_id=100)])
        app = _make_app(db, moodle=moodle)

        pdf_bytes = b"%PDF-1.4 fake content"
        with (
            patch(
                "sophia.services.material_index.extract_full_pdf_text",
                return_value="Extracted text from PDF",
            ) as mock_extract,
            patch(
                "sophia.services.material_index._download_pdf",
                new_callable=AsyncMock,
                return_value=pdf_bytes,
            ),
        ):
            materials = await scrape_course_materials(app, course_id=42)

        assert len(materials) == 1
        assert materials[0].name == "Lecture Slides"
        assert materials[0].course_id == 42
        assert materials[0].module_id == 100
        mock_extract.assert_called_once_with(pdf_bytes)

        # Verify DB persistence
        cursor = await db.execute("SELECT COUNT(*) FROM course_materials WHERE course_id=42")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_scrape_idempotent(self, db: aiosqlite.Connection) -> None:
        moodle = MagicMock()
        moodle.get_course_resources = AsyncMock(return_value=[_make_resource_module(module_id=100)])
        app = _make_app(db, moodle=moodle)

        pdf_bytes = b"%PDF-1.4 fake"
        with (
            patch(
                "sophia.services.material_index.extract_full_pdf_text",
                return_value="Some text",
            ),
            patch(
                "sophia.services.material_index._download_pdf",
                new_callable=AsyncMock,
                return_value=pdf_bytes,
            ),
        ):
            first = await scrape_course_materials(app, course_id=42)
            second = await scrape_course_materials(app, course_id=42)

        assert len(first) == 1
        assert len(second) == 0  # already scraped, skipped

        cursor = await db.execute("SELECT COUNT(*) FROM course_materials WHERE course_id=42")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_scrape_skips_non_pdf(self, db: aiosqlite.Connection) -> None:
        moodle = MagicMock()
        non_pdf = ModuleInfo(
            id=200,
            name="Course Page",
            modname="resource",
            url="https://tuwel.tuwien.ac.at/mod/resource/view.php?id=200",
            contents=[
                ContentInfo(
                    filename="page.html",
                    fileurl="https://tuwel.tuwien.ac.at/page.html",
                    filesize=512,
                    mimetype="text/html",
                )
            ],
        )
        moodle.get_course_resources = AsyncMock(return_value=[non_pdf])
        app = _make_app(db, moodle=moodle)

        materials = await scrape_course_materials(app, course_id=42)
        assert len(materials) == 0


# ---------------------------------------------------------------------------
# index_materials (async, needs DB + mocked embedder/store)
# ---------------------------------------------------------------------------


class TestIndexMaterials:
    @pytest.mark.asyncio
    async def test_index_pending_materials(self, db: aiosqlite.Connection) -> None:
        # Seed a pending material with pdf_text
        await db.execute(
            "INSERT INTO course_materials"
            " (course_id, module_id, name, url, mimetype, pdf_text, status)"
            " VALUES (42, 100, 'Slides', 'https://x.com/s.pdf', 'application/pdf',"
            "  'This is the extracted PDF content for testing.', 'pending')",
        )
        await db.commit()

        app = _make_app(db)
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]
        mock_store = MagicMock()

        with (
            patch("sophia.services.material_index._create_embedder", return_value=mock_embedder),
            patch("sophia.services.material_index._create_store", return_value=mock_store),
        ):
            total = await index_materials(app, course_id=42)

        assert total >= 1
        mock_store.add_chunks.assert_called_once()

        # Verify chunks passed to store have source="pdf"
        stored_chunks = mock_store.add_chunks.call_args[0][0]
        assert all(c.source == "pdf" for c in stored_chunks)

        # Verify DB updated
        cursor = await db.execute(
            "SELECT status, chunk_count FROM course_materials WHERE course_id=42"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "completed"
        assert row[1] >= 1

    @pytest.mark.asyncio
    async def test_index_skips_completed(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "INSERT INTO course_materials"
            " (course_id, module_id, name, url, mimetype, pdf_text, chunk_count, status)"
            " VALUES (42, 100, 'Slides', 'https://x.com/s.pdf', 'application/pdf',"
            "  'Already indexed.', 5, 'completed')",
        )
        await db.commit()

        app = _make_app(db)
        with (
            patch("sophia.services.material_index._create_embedder") as mock_emb,
            patch("sophia.services.material_index._create_store"),
        ):
            total = await index_materials(app, course_id=42)

        assert total == 0
        mock_emb.assert_not_called()

    @pytest.mark.asyncio
    async def test_index_skips_empty_text(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "INSERT INTO course_materials"
            " (course_id, module_id, name, url, mimetype, pdf_text, status)"
            " VALUES (42, 100, 'Empty', 'https://x.com/e.pdf', 'application/pdf',"
            "  '', 'pending')",
        )
        await db.commit()

        app = _make_app(db)
        with (
            patch("sophia.services.material_index._create_embedder") as mock_emb,
            patch("sophia.services.material_index._create_store"),
        ):
            total = await index_materials(app, course_id=42)

        assert total == 0
        mock_emb.assert_not_called()
