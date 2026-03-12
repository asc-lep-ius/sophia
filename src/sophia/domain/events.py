"""Domain events — frozen dataclasses for decoupled communication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sophia.domain.models import Format, ReferenceSource


@dataclass(frozen=True)
class CoursesFetched:
    """Emitted after enrolled courses are retrieved."""

    count: int
    course_names: tuple[str, ...]


@dataclass(frozen=True)
class BookFound:
    """Emitted when a book reference is extracted from course content."""

    title: str
    isbn: str | None
    course_name: str
    source: ReferenceSource


@dataclass(frozen=True)
class SearchCompleted:
    """Emitted after searching for a book across sources."""

    title: str
    isbn: str | None
    result_count: int
    open_access_found: bool


@dataclass(frozen=True)
class DownloadStarted:
    """Emitted when a file download begins."""

    title: str
    format: Format
    total_bytes: int | None


@dataclass(frozen=True)
class DownloadProgress:
    """Emitted periodically during a download."""

    title: str
    bytes_downloaded: int
    total_bytes: int | None
    speed_bps: float


@dataclass(frozen=True)
class DownloadCompleted:
    """Emitted when a file download finishes successfully."""

    title: str
    path: Path
    saved_amount: float | None


@dataclass(frozen=True)
class DownloadFailed:
    """Emitted when a file download fails."""

    title: str
    error: str


@dataclass(frozen=True)
class ReportGenerated:
    """Emitted when a Typst report is rendered."""

    path: Path


@dataclass(frozen=True)
class ExtractionReport:
    """Summary of a multi-course extraction run."""

    total_courses: int
    successful: int
    failed: list[tuple[str, str]]
    total_references: int


@dataclass(frozen=True)
class LectureDownloadStarted:
    """Emitted when a lecture media download begins."""

    episode_id: str
    title: str
    track_url: str


@dataclass(frozen=True)
class LectureDownloadCompleted:
    """Emitted when a lecture download finishes successfully."""

    episode_id: str
    title: str
    file_path: Path
    file_size_bytes: int


@dataclass(frozen=True)
class LectureDownloadFailed:
    """Emitted when a lecture download fails."""

    episode_id: str
    title: str
    error: str
