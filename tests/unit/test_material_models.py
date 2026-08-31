"""Tests for the course material domain models.

The schema those models map to is verified against Postgres by the Alembic
baseline tests; what is left here is the model behaviour itself.
"""

from __future__ import annotations

import pytest

from sophia.domain.models import CourseMaterial, KnowledgeChunk, MaterialSource


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
