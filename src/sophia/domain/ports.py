"""Port protocols — hexagonal architecture boundaries.

Protocols follow Interface Segregation: consumers depend only on what they need.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sophia.domain.models import (
        AssignmentInfo,
        BookReference,
        CheckmarkInfo,
        Course,
        CourseSection,
        DownloadProgressEvent,
        GradeItem,
        ModuleInfo,
        QuizInfo,
        ReferenceSource,
        ReportData,
        SearchResult,
    )


class CourseProvider(Protocol):
    """Core course enumeration — used by all modules."""

    async def get_enrolled_courses(self, classification: str = "inprogress") -> list[Course]: ...

    async def get_course_content(self, course_id: int) -> list[CourseSection]: ...


class ResourceProvider(Protocol):
    """Course resource access — used by Bücherwurm."""

    async def get_course_books(self, course_ids: list[int]) -> list[ModuleInfo]: ...
    async def get_course_pages(self, course_ids: list[int]) -> list[ModuleInfo]: ...
    async def get_course_resources(self, course_ids: list[int]) -> list[ModuleInfo]: ...
    async def get_course_urls(self, course_ids: list[int]) -> list[ModuleInfo]: ...


class AssignmentProvider(Protocol):
    """Deadline & grade access — used by Chronos and Athena."""

    async def get_assignments(self, course_ids: list[int]) -> list[AssignmentInfo]: ...
    async def get_quizzes(self, course_ids: list[int]) -> list[QuizInfo]: ...
    async def get_checkmarks(self, course_ids: list[int]) -> list[CheckmarkInfo]: ...
    async def get_grade_items(self, course_id: int) -> list[GradeItem]: ...


class BookSearcher(Protocol):
    """Searches for books across sources."""

    async def search(self, reference: BookReference) -> list[SearchResult]: ...


class Downloader(Protocol):
    """Downloads files with progress reporting."""

    async def download(
        self, result: SearchResult, dest: Path
    ) -> AsyncIterator[DownloadProgressEvent]: ...


class ReferenceExtractor(Protocol):
    """Extracts book references from content (sync, CPU-bound)."""

    def extract(
        self, content: str, source: ReferenceSource, course_id: int
    ) -> list[BookReference]: ...


class AsyncReferenceExtractor(Protocol):
    """Extracts book references via I/O (LLM APIs)."""

    async def extract(
        self, content: str, source: ReferenceSource, course_id: int
    ) -> list[BookReference]: ...


class ReportRenderer(Protocol):
    """Renders data into formatted reports."""

    async def render(self, data: ReportData, output: Path) -> Path: ...
