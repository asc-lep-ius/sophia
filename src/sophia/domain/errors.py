"""Domain error hierarchy."""

from __future__ import annotations


class SophiaError(Exception):
    """Base error for all Sophia exceptions."""


class AuthError(SophiaError):
    """Authentication failed — token expired or invalid."""


class MoodleError(SophiaError):
    """Moodle API returned an error response."""


class SearchError(SophiaError):
    """Book search failed."""


class DownloadError(SophiaError):
    """File download failed."""


class ExtractionError(SophiaError):
    """Reference extraction failed."""


class RenderError(SophiaError):
    """Report rendering failed."""


class TissError(SophiaError):
    """TISS API request failed."""


class RegistrationError(SophiaError):
    """Course or group registration failed."""


class NetworkError(RegistrationError):
    """Network connectivity failure — host unreachable or timeout."""


class HermesError(SophiaError):
    """Hermes lecture pipeline error."""


class HermesSetupError(HermesError):
    """Hermes setup/configuration error."""


class LectureTubeError(HermesError):
    """LectureTube API request failed."""


class LectureDownloadError(HermesError):
    """Lecture media download failed."""


class TranscriptionError(HermesError):
    """Whisper transcription failed."""


class EmbeddingError(HermesError):
    """Embedding or knowledge base indexing failed."""


class AthenaError(SophiaError):
    """Athena study companion error."""


class TopicExtractionError(AthenaError):
    """Topic extraction from content failed."""


class ConfidenceError(AthenaError):
    """Confidence assessment workflow failed."""


class StudySessionError(AthenaError):
    """Study session workflow failed."""


class CardReviewError(AthenaError):
    """Card review workflow failed."""


class EngagementPolicyUnmet(AthenaError):
    """An answer was submitted without the learning process the question requires.

    ``params`` names what is missing so the study surface can prompt for the
    step that was skipped instead of dead-ending the learner.
    """

    def __init__(self, message: str, params: dict[str, str | int] | None = None) -> None:
        super().__init__(message)
        self.params = params or {}


class ChronosError(SophiaError):
    """Chronos deadline pipeline error."""
