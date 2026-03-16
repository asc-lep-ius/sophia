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


@dataclass(frozen=True)
class TranscriptionStarted:
    """Emitted when transcription of a lecture begins."""

    episode_id: str
    title: str


@dataclass(frozen=True)
class TranscriptionCompleted:
    """Emitted when transcription finishes successfully."""

    episode_id: str
    title: str
    segment_count: int
    duration_s: float


@dataclass(frozen=True)
class TranscriptionFailed:
    """Emitted when transcription fails."""

    episode_id: str
    title: str
    error: str


@dataclass(frozen=True)
class IndexingStarted:
    """Emitted when indexing of lecture transcripts begins."""

    episode_id: str
    title: str


@dataclass(frozen=True)
class IndexingCompleted:
    """Emitted when indexing finishes successfully."""

    episode_id: str
    title: str
    chunk_count: int


@dataclass(frozen=True)
class IndexingFailed:
    """Emitted when indexing fails."""

    episode_id: str
    title: str
    error: str


@dataclass(frozen=True)
class TopicsExtracted:
    """Emitted after topics are extracted from course content."""

    course_id: int
    topic_count: int
    source: str  # "lecture" or "quiz"


@dataclass(frozen=True)
class TopicLectureLinked:
    """Emitted when a topic is cross-referenced with lecture chunks."""

    topic: str
    course_id: int
    chunk_count: int


@dataclass(frozen=True)
class ConfidenceAssessed:
    """Emitted after a confidence-before-reveal cycle completes."""

    course_id: int
    topics_rated: int
    blind_spots: int
    avg_calibration_error: float
