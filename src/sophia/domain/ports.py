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
        KnowledgeChunk,
        Lecture,
        ModuleInfo,
        QuizInfo,
        ReferenceSource,
        RegistrationGroup,
        RegistrationResult,
        RegistrationTarget,
        ReportData,
        SearchResult,
        TissCourseInfo,
        TissExamDate,
        TranscriptSegment,
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


class CourseMetadataProvider(Protocol):
    """Course metadata from external sources (TISS)."""

    async def get_course_details(self, course_number: str, semester: str) -> TissCourseInfo: ...
    async def get_exam_dates(self, course_number: str) -> list[TissExamDate]: ...


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


class RegistrationProvider(Protocol):
    """TISS course/group registration — used by Kairos."""

    async def get_registration_status(
        self, course_number: str, semester: str
    ) -> RegistrationTarget: ...

    async def get_groups(self, course_number: str, semester: str) -> list[RegistrationGroup]: ...

    async def register(
        self, course_number: str, semester: str, group_id: str | None = None
    ) -> RegistrationResult: ...


class LectureProvider(Protocol):
    """Lecture discovery from TUWEL Opencast modules — used by Hermes."""

    async def get_series_episodes(self, module_id: int) -> list[Lecture]: ...
    async def get_episode_detail(self, module_id: int, episode_id: str) -> Lecture | None: ...


class LectureDownloader(Protocol):
    """Downloads lecture media tracks with progress reporting and resume."""

    async def download_track(
        self, url: str, dest: Path
    ) -> AsyncIterator[DownloadProgressEvent]: ...


class Transcriber(Protocol):
    """Transcribes audio files into text segments."""

    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]: ...


class Embedder(Protocol):
    """Embeds text chunks into dense vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, query: str) -> list[float]: ...


class KnowledgeStore(Protocol):
    """Vector store for semantic search over lecture content."""

    def add_chunks(self, chunks: list[KnowledgeChunk], embeddings: list[list[float]]) -> None: ...

    def search(
        self,
        query_embedding: list[float],
        *,
        n_results: int = 5,
        episode_ids: list[str] | None = None,
    ) -> list[tuple[KnowledgeChunk, float]]: ...

    def has_episode(self, episode_id: str) -> bool: ...


class TopicExtractor(Protocol):
    """Uses LLM to extract topic labels from text content."""

    async def extract_topics(self, text: str, course_context: str = "") -> list[str]: ...
