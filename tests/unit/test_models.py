"""Tests for domain models."""

from __future__ import annotations

import pytest

from sophia.domain.models import (
    BookReference,
    ContentInfo,
    Course,
    CourseSection,
    DownloadJob,
    DownloadStatus,
    Format,
    ModuleInfo,
    ReferenceSource,
    SearchResult,
)


class TestEnums:
    """Verify all enum members exist."""

    def test_reference_source_values(self):
        assert set(ReferenceSource) == {
            ReferenceSource.DESCRIPTION,
            ReferenceSource.SYLLABUS,
            ReferenceSource.PAGE,
            ReferenceSource.RESOURCE_NAME,
            ReferenceSource.PDF,
            ReferenceSource.LLM,
            ReferenceSource.TISS,
        }

    def test_format_values(self):
        assert set(Format) == {Format.PDF, Format.EPUB, Format.DJVU, Format.MOBI}

    def test_download_status_values(self):
        assert set(DownloadStatus) == {
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
        }

    def test_strenum_string_values(self):
        assert str(Format.PDF) == "pdf"
        assert str(DownloadStatus.QUEUED) == "queued"
        assert str(ReferenceSource.LLM) == "llm"


class TestCourse:
    """Tests for Course model."""

    def test_create_with_required_fields(self):
        course = Course(id=1, fullname="Linear Algebra", shortname="LA")
        assert course.id == 1
        assert course.fullname == "Linear Algebra"
        assert course.shortname == "LA"
        assert course.url is None

    def test_create_with_url(self):
        course = Course(
            id=42,
            fullname="Analysis 1",
            shortname="AN1",
            url="https://tuwel.tuwien.ac.at/course/view.php?id=42",
        )
        assert course.url is not None


class TestBookReference:
    """Tests for BookReference model."""

    def test_defaults(self):
        ref = BookReference(
            title="Introduction to Algorithms",
            source=ReferenceSource.DESCRIPTION,
            course_id=1,
        )
        assert ref.authors == []
        assert ref.isbn is None
        assert ref.course_name == ""
        assert ref.confidence == 1.0

    def test_full_creation(self):
        ref = BookReference(
            title="CLRS",
            authors=["Cormen", "Leiserson", "Rivest", "Stein"],
            isbn="978-0-262-04630-5",
            source=ReferenceSource.SYLLABUS,
            course_id=10,
            course_name="Algorithms",
            confidence=0.85,
        )
        assert len(ref.authors) == 4
        assert ref.confidence == 0.85


class TestSearchResult:
    """Tests for SearchResult model."""

    def test_valid_search_result(self):
        result = SearchResult(
            title="Test Book",
            authors=["Author A"],
            isbn="978-3-16-148410-0",
            format=Format.PDF,
            size_bytes=1_000_000,
            language="en",
            year=2023,
            md5="abc123",
            download_url="https://example.com/book.pdf",
            source_name="Open Access",
        )
        assert result.is_open_access is False
        assert result.size_bytes == 1_000_000

    def test_open_access_flag(self):
        result = SearchResult(
            title="Open Book",
            authors=[],
            isbn=None,
            format=Format.EPUB,
            size_bytes=500_000,
            language="de",
            year=None,
            md5="def456",
            download_url="https://example.com/open.epub",
            source_name="DOAB",
            is_open_access=True,
        )
        assert result.is_open_access is True


class TestCourseStructure:
    """Tests for CourseSection, ModuleInfo, and ContentInfo."""

    def test_content_info(self):
        content = ContentInfo(
            filename="syllabus.pdf",
            fileurl="https://tuwel.example.com/file.php/1/syllabus.pdf",
            filesize=204800,
            mimetype="application/pdf",
        )
        assert content.filename == "syllabus.pdf"

    def test_module_info_defaults(self):
        module = ModuleInfo(id=1, name="Resources", modname="folder")
        assert module.url is None
        assert module.contents == []

    def test_course_section(self):
        content = ContentInfo(
            filename="notes.pdf",
            fileurl="https://example.com/notes.pdf",
            filesize=1024,
        )
        module = ModuleInfo(id=10, name="Week 1", modname="resource", contents=[content])
        section = CourseSection(
            id=1, name="Introduction", summary="<p>Welcome</p>", modules=[module]
        )
        assert len(section.modules) == 1
        assert len(section.modules[0].contents) == 1


def _make_job() -> DownloadJob:
    """Factory for a DownloadJob with minimal valid data."""
    ref = BookReference(
        title="Test Book",
        source=ReferenceSource.DESCRIPTION,
        course_id=1,
    )
    result = SearchResult(
        title="Test Book",
        authors=["Author"],
        isbn=None,
        format=Format.PDF,
        size_bytes=100,
        language="en",
        year=2024,
        md5="abc",
        download_url="https://example.com/book.pdf",
        source_name="test",
    )
    return DownloadJob(reference=ref, result=result)


class TestDownloadJob:
    """Tests for DownloadJob state machine."""

    def test_initial_state(self):
        job = _make_job()
        assert job.status == DownloadStatus.QUEUED
        assert job.progress_bytes == 0
        assert job.dest_path is None
        assert job.error is None

    def test_valid_transition_queued_to_downloading(self):
        job = _make_job()
        job.transition(DownloadStatus.DOWNLOADING)
        assert job.status == DownloadStatus.DOWNLOADING

    def test_valid_transition_downloading_to_completed(self):
        job = _make_job()
        job.transition(DownloadStatus.DOWNLOADING)
        job.transition(DownloadStatus.COMPLETED)
        assert job.status == DownloadStatus.COMPLETED

    def test_valid_transition_downloading_to_failed(self):
        job = _make_job()
        job.transition(DownloadStatus.DOWNLOADING)
        job.transition(DownloadStatus.FAILED, error="Network timeout")
        assert job.status == DownloadStatus.FAILED
        assert job.error == "Network timeout"

    def test_invalid_transition_completed_to_queued(self):
        job = _make_job()
        job.transition(DownloadStatus.DOWNLOADING)
        job.transition(DownloadStatus.COMPLETED)
        with pytest.raises(ValueError, match="Invalid transition"):
            job.transition(DownloadStatus.QUEUED)

    def test_invalid_transition_queued_to_completed(self):
        job = _make_job()
        with pytest.raises(ValueError, match="Invalid transition"):
            job.transition(DownloadStatus.COMPLETED)

    def test_retry_resets_progress(self):
        job = _make_job()
        job.transition(DownloadStatus.DOWNLOADING)
        job.progress_bytes = 5000
        job.transition(DownloadStatus.FAILED, error="oops")
        assert job.error == "oops"

        # Retry: FAILED → QUEUED resets progress
        job.transition(DownloadStatus.QUEUED)
        assert job.status == DownloadStatus.QUEUED
        assert job.progress_bytes == 0
        assert job.error is None

    def test_failed_to_queued_allowed(self):
        job = _make_job()
        job.transition(DownloadStatus.FAILED)
        job.transition(DownloadStatus.QUEUED)
        assert job.status == DownloadStatus.QUEUED
