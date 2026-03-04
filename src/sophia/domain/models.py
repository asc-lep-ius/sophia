"""Pure domain models — no external dependencies except Pydantic."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from pathlib import Path


# --- Enums (defined before models that reference them) ---


class ReferenceSource(StrEnum):
    """Origin of a book reference extraction."""

    DESCRIPTION = "description"
    SYLLABUS = "syllabus"
    PAGE = "page"
    RESOURCE_NAME = "resource_name"
    PDF = "pdf"
    LLM = "llm"


class Format(StrEnum):
    """Supported e-book file formats."""

    PDF = "pdf"
    EPUB = "epub"
    DJVU = "djvu"
    MOBI = "mobi"


class DownloadStatus(StrEnum):
    """Lifecycle states for a download job."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


# --- Value objects (Pydantic models) ---


class Course(BaseModel):
    """A TUWEL/Moodle course."""

    id: int
    fullname: str
    shortname: str
    url: str | None = None


class BookReference(BaseModel):
    """A reference to a book extracted from course content."""

    title: str
    authors: list[str] = []
    isbn: str | None = None
    source: ReferenceSource
    course_id: int
    course_name: str = ""
    confidence: float = 1.0


class SearchResult(BaseModel):
    """A single result from a book search source."""

    title: str
    authors: list[str]
    isbn: str | None
    format: Format
    size_bytes: int
    language: str
    year: int | None
    md5: str
    download_url: str
    source_name: str
    is_open_access: bool = False


class ContentInfo(BaseModel):
    """A single file/content item within a Moodle module."""

    filename: str
    fileurl: str
    filesize: int
    mimetype: str = ""


class ModuleInfo(BaseModel):
    """A Moodle activity/resource module."""

    id: int
    name: str
    modname: str
    url: str | None = None
    description: str = ""
    contents: list[ContentInfo] = []


class CourseSection(BaseModel):
    """A section within a Moodle course."""

    id: int
    name: str
    summary: str
    modules: list[ModuleInfo]


# --- Placeholder models for ports (will be fleshed out in later phases) ---


class AssignmentInfo(BaseModel):
    """Placeholder for assignment data (Chronos phase)."""

    id: int
    name: str
    course_id: int
    due_date: str | None = None


class QuizInfo(BaseModel):
    """Placeholder for quiz data (Athena phase)."""

    id: int
    name: str
    course_id: int


class CheckmarkInfo(BaseModel):
    """Placeholder for checkmark/completion data."""

    id: int
    name: str
    course_id: int
    completed: bool = False


class GradeItem(BaseModel):
    """Placeholder for grade item data."""

    id: int
    name: str
    grade: float | None = None
    max_grade: float | None = None


class ReportData(BaseModel):
    """Placeholder for report rendering input."""

    title: str
    content: str = ""


class DownloadProgressEvent(BaseModel):
    """Progress update yielded during a download."""

    bytes_downloaded: int
    total_bytes: int | None
    speed_bps: float = 0.0


# --- Mutable application state ---


_ALLOWED_TRANSITIONS: dict[DownloadStatus, set[DownloadStatus]] = {
    DownloadStatus.QUEUED: {DownloadStatus.DOWNLOADING, DownloadStatus.FAILED},
    DownloadStatus.DOWNLOADING: {DownloadStatus.COMPLETED, DownloadStatus.FAILED},
    DownloadStatus.COMPLETED: set(),
    DownloadStatus.FAILED: {DownloadStatus.QUEUED},
}


class DownloadJob:
    """Mutable download state — managed by DownloadManager, not a domain entity.

    Uses an explicit state machine to prevent illegal transitions
    (e.g., COMPLETED → QUEUED) and ensure retry logic resets progress.
    """

    __slots__ = (
        "reference",
        "result",
        "status",
        "progress_bytes",
        "total_bytes",
        "dest_path",
        "error",
    )

    def __init__(self, reference: BookReference, result: SearchResult) -> None:
        self.reference = reference
        self.result = result
        self.status: DownloadStatus = DownloadStatus.QUEUED
        self.progress_bytes: int = 0
        self.total_bytes: int | None = None
        self.dest_path: Path | None = None
        self.error: str | None = None

    def transition(self, new_status: DownloadStatus, *, error: str | None = None) -> None:
        """Transition to a new status with guard checks."""
        allowed = _ALLOWED_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            msg = (
                f"Invalid transition: {self.status.value} → {new_status.value}. "
                f"Allowed: {', '.join(s.value for s in allowed) or 'none (terminal)'}"
            )
            raise ValueError(msg)
        if new_status == DownloadStatus.QUEUED:
            self.progress_bytes = 0
            self.error = None
        if error is not None:
            self.error = error
        self.status = new_status
