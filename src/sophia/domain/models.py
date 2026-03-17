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
    TISS = "tiss"


class ResourceCategory(StrEnum):
    """Category of a course resource (URL activity)."""

    BOOK = "book"
    TUTORIAL = "tutorial"
    DOCUMENTATION = "documentation"
    PRACTICE = "practice"
    TOOL = "tool"
    OTHER = "other"


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
    SKIPPED = "skipped"
    FAILED = "failed"
    DISCARDED = "discarded"


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


class CourseResource(BaseModel):
    """A classified URL resource from a course page."""

    url: str
    title: str
    category: ResourceCategory
    course_id: int
    course_name: str = ""
    description: str = ""


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


class RegistrationStatus(StrEnum):
    """Status of a registration attempt."""

    PENDING = "pending"
    OPEN = "open"
    REGISTERED = "registered"
    FULL = "full"
    CLOSED = "closed"
    FAILED = "failed"


class RegistrationType(StrEnum):
    """Type of TISS registration."""

    LVA = "lva"
    GROUP = "group"
    EXAM = "exam"


class RegistrationGroup(BaseModel):
    """A group/timeslot within a TISS course."""

    group_id: str
    name: str
    day: str = ""
    time_start: str = ""
    time_end: str = ""
    location: str = ""
    capacity: int = 0
    enrolled: int = 0
    status: RegistrationStatus = RegistrationStatus.PENDING
    register_button_id: str = ""


class RegistrationTarget(BaseModel):
    """A course registration target with preference-ordered groups."""

    course_number: str
    semester: str
    registration_type: RegistrationType
    title: str = ""
    registration_start: str | None = None
    registration_end: str | None = None
    status: RegistrationStatus = RegistrationStatus.PENDING
    groups: list[RegistrationGroup] = []
    preferred_group_ids: list[str] = []


class RegistrationResult(BaseModel):
    """Outcome of a registration attempt."""

    course_number: str
    registration_type: RegistrationType
    success: bool
    group_name: str = ""
    message: str = ""
    attempted_at: str = ""


class FavoriteCourse(BaseModel, frozen=True):
    """A course from the TISS favorites page."""

    course_number: str
    title: str
    course_type: str  # VU, VO, UE, SE, etc.
    semester: str
    hours: float
    ects: float
    lva_registered: bool = False
    group_registered: bool = False
    exam_registered: bool = False


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
    DownloadStatus.DOWNLOADING: {
        DownloadStatus.COMPLETED,
        DownloadStatus.SKIPPED,
        DownloadStatus.FAILED,
    },
    DownloadStatus.COMPLETED: {DownloadStatus.DISCARDED},
    DownloadStatus.SKIPPED: {DownloadStatus.QUEUED, DownloadStatus.DISCARDED},
    DownloadStatus.FAILED: {DownloadStatus.QUEUED, DownloadStatus.DISCARDED},
    DownloadStatus.DISCARDED: {DownloadStatus.QUEUED},
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


# --- Hermes (lecture pipeline) models ---


class WhisperModel(StrEnum):
    """Supported Whisper model sizes."""

    LARGE_V3 = "large-v3"
    TURBO = "turbo"
    MEDIUM = "medium"
    SMALL = "small"


class ComputeDevice(StrEnum):
    """Hardware compute target."""

    CUDA = "cuda"
    CPU = "cpu"


class ComputeType(StrEnum):
    """Numeric precision for inference."""

    FLOAT16 = "float16"
    INT8 = "int8"
    INT8_FLOAT16 = "int8_float16"
    FLOAT32 = "float32"


class LLMProvider(StrEnum):
    """Supported LLM providers."""

    GITHUB = "github"
    GEMINI = "gemini"
    GROQ = "groq"
    OLLAMA = "ollama"


class EmbeddingProvider(StrEnum):
    """Embedding model source."""

    LOCAL = "local"
    GITHUB = "github"
    GEMINI = "gemini"


class HermesWhisperConfig(BaseModel, frozen=True):
    """Whisper transcription engine configuration."""

    model: WhisperModel = WhisperModel.LARGE_V3
    device: ComputeDevice = ComputeDevice.CPU
    compute_type: ComputeType = ComputeType.FLOAT32
    vad_filter: bool = True
    language: str = "de"


class HermesLLMConfig(BaseModel, frozen=True):
    """LLM provider for classification, summaries, quiz generation."""

    provider: LLMProvider = LLMProvider.GITHUB
    model: str = "openai/gpt-4o"
    api_key_env: str = "GITHUB_TOKEN"


class HermesEmbeddingConfig(BaseModel, frozen=True):
    """Embedding model for vector search."""

    provider: EmbeddingProvider = EmbeddingProvider.LOCAL
    model: str = "intfloat/multilingual-e5-large"


class HermesConfig(BaseModel, frozen=True):
    """Complete Hermes module configuration."""

    whisper: HermesWhisperConfig = HermesWhisperConfig()
    llm: HermesLLMConfig = HermesLLMConfig()
    embeddings: HermesEmbeddingConfig = HermesEmbeddingConfig()


# ---------------------------------------------------------------------------
# Hermes — Lecture models
# ---------------------------------------------------------------------------


class LectureTrack(BaseModel, frozen=True):
    """A single media track (video/audio) of a lecture."""

    flavor: str
    url: str
    mimetype: str
    resolution: str = ""


class Lecture(BaseModel, frozen=True):
    """A single lecture recording (Opencast episode)."""

    episode_id: str
    title: str
    series_id: str
    series_title: str = ""
    duration_ms: int = 0
    created: str = ""
    creator: str = ""
    tracks: list[LectureTrack] = []


# ---------------------------------------------------------------------------
# Scheduler — Job scheduling models
# ---------------------------------------------------------------------------


class JobStatus(StrEnum):
    """Lifecycle states for a scheduled job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduledJob(BaseModel, frozen=True):
    """A job scheduled to run at a specific time via OS-native scheduler."""

    job_id: str
    command: str
    scheduled_for: str
    created_at: str
    status: JobStatus = JobStatus.PENDING
    description: str = ""


# ---------------------------------------------------------------------------
# Transcription — Whisper transcription models
# ---------------------------------------------------------------------------


class TranscriptSegment(BaseModel, frozen=True):
    """A single segment from a lecture transcription."""

    start: float  # seconds
    end: float  # seconds
    text: str


# ---------------------------------------------------------------------------
# Knowledge Base — Embedding + Search models
# ---------------------------------------------------------------------------


class KnowledgeChunk(BaseModel, frozen=True):
    """A text chunk prepared for embedding and vector search."""

    chunk_id: str
    episode_id: str
    chunk_index: int
    text: str
    start_time: float
    end_time: float


class LectureSearchResult(BaseModel, frozen=True):
    """A single result from semantic search over lecture transcripts."""

    episode_id: str
    title: str
    chunk_text: str
    start_time: float
    end_time: float
    score: float


# ---------------------------------------------------------------------------
# Athena — Study companion models
# ---------------------------------------------------------------------------


class TopicSource(StrEnum):
    """Origin of a topic mapping."""

    LECTURE = "lecture"
    QUIZ = "quiz"
    MANUAL = "manual"


class TopicMapping(BaseModel, frozen=True):
    """A topic extracted from course content (lecture or quiz)."""

    topic: str
    course_id: int
    source: TopicSource = TopicSource.LECTURE
    frequency: int = 1


class TopicLectureLink(BaseModel, frozen=True):
    """Links a topic to a specific lecture transcript chunk."""

    topic: str
    course_id: int
    chunk_id: str
    episode_id: str
    score: float  # embedding similarity score


class ConfidenceRating(BaseModel, frozen=True):
    """A student's self-assessed confidence vs actual performance for a topic."""

    topic: str
    course_id: int
    predicted: float  # 0.0 to 1.0 (from student's 1-5 rating mapped to 0-1)
    actual: float | None = None  # populated later from card recall or quiz score
    rated_at: str = ""  # ISO timestamp

    @property
    def calibration_error(self) -> float | None:
        """Signed difference: predicted - actual. Positive = overconfident."""
        if self.actual is None:
            return None
        return self.predicted - self.actual

    @property
    def is_blind_spot(self) -> bool:
        """Topic where student is significantly overconfident (>0.2 delta)."""
        err = self.calibration_error
        return err is not None and err > 0.2


class StudySession(BaseModel, frozen=True):
    """A pre-test → study → post-test learning session."""

    id: int = 0
    course_id: int
    topic: str
    pre_test_score: float | None = None  # 0.0-1.0
    post_test_score: float | None = None  # 0.0-1.0
    started_at: str = ""
    completed_at: str | None = None

    @property
    def improvement(self) -> float | None:
        """Post-test score minus pre-test score. Positive = learned."""
        if self.pre_test_score is None or self.post_test_score is None:
            return None
        return self.post_test_score - self.pre_test_score


class FlashcardSource(StrEnum):
    """Origin of a flashcard."""

    STUDY = "study"
    LECTURE = "lecture"
    MANUAL = "manual"


class StudentFlashcard(BaseModel, frozen=True):
    """A flashcard authored or adopted by the student."""

    id: int = 0
    course_id: int
    topic: str
    front: str  # question
    back: str  # answer
    source: FlashcardSource = FlashcardSource.STUDY
    created_at: str = ""


class CardReviewAttempt(BaseModel, frozen=True):
    """Record of a single flashcard review attempt."""

    id: int = 0
    flashcard_id: int
    success: bool
    reviewed_at: str = ""


class SelfExplanation(BaseModel, frozen=True):
    """A student's self-explanation of why they got a question wrong."""

    id: int = 0
    flashcard_id: int
    student_explanation: str
    scaffold_level: int = 3  # 3=full, 1=minimal, 0=open
    created_at: str = ""


REVIEW_INTERVALS = [1, 3, 7, 14, 30]  # days


class ReviewSchedule(BaseModel, frozen=True):
    """Spaced review schedule for a topic."""

    topic: str
    course_id: int
    interval_index: int = 0  # index into REVIEW_INTERVALS
    last_reviewed_at: str | None = None
    next_review_at: str
    score_at_last_review: float | None = None

    @property
    def interval_days(self) -> int:
        """Current interval in days."""
        idx = min(self.interval_index, len(REVIEW_INTERVALS) - 1)
        return REVIEW_INTERVALS[idx]

    @property
    def is_due(self) -> bool:
        """Whether review is due (next_review_at <= now)."""
        from datetime import UTC, datetime

        return datetime.fromisoformat(self.next_review_at) <= datetime.now(UTC)
