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


# --- TISS models ---


class TissCourseInfo(BaseModel):
    """Course metadata from the TISS public API."""

    course_number: str
    semester: str
    course_type: str = ""  # "VU", "UE", "SE", "VO", etc.
    title_de: str = ""
    title_en: str = ""
    ects: float = 0.0
    description_de: str = ""
    description_en: str = ""
    objectives_de: str = ""
    objectives_en: str = ""


class TissExamDate(BaseModel):
    """An exam date from the TISS public API."""

    exam_id: str
    course_number: str
    title: str = ""
    date_start: str | None = None
    date_end: str | None = None
    registration_start: str | None = None
    registration_end: str | None = None
    mode: str = ""  # "WRITTEN", "ORAL", etc.


# --- Placeholder models for ports (will be fleshed out in later phases) ---


class AssignmentInfo(BaseModel):
    """An assignment from the TUWEL assignment index page."""

    id: int  # Course module ID (cmid)
    name: str
    course_id: int
    due_date: str | None = None  # UNIX timestamp as string, or None
    submission_status: str = ""
    grade: str | None = None
    url: str | None = None
    is_restricted: bool = False


class QuizInfo(BaseModel):
    """Placeholder for quiz data (Athena phase)."""

    id: int
    name: str
    course_id: int


class CheckmarkInfo(BaseModel):
    """Checkmark (Kreuzerlübung) data — extracted from the grade report."""

    id: int
    name: str
    course_id: int
    grade: str | None = None
    max_grade: str | None = None
    completed: bool = False
    url: str | None = None


class GradeItem(BaseModel):
    """A grade item from the TUWEL grade report."""

    id: int
    name: str
    item_type: str = ""
    grade: str | None = None
    max_grade: str | None = None
    weight: str | None = None
    percentage: str | None = None
    feedback: str = ""
    url: str | None = None
    category: str = ""


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
