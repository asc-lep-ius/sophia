"""Study API response DTOs."""

from __future__ import annotations

from enum import StrEnum

from sophia.api.schemas.common import ApiModel
from sophia.api.schemas.content import ContentLanguage  # noqa: TC001
from sophia.api.schemas.provenance import Provenance  # noqa: TC001
from sophia.api.schemas.questions import Question  # noqa: TC001
from sophia.api.schemas.study.requests import (  # noqa: TC001
    StudyAttemptPhase,
    StudyFlashcardSource,
)


class CalibrationBand(StrEnum):
    """Verdict on a learner's prediction against their measured performance."""

    UNKNOWN = "unknown"
    WELL_CALIBRATED = "well_calibrated"
    OVERCONFIDENT = "overconfident"
    UNDERCONFIDENT = "underconfident"


class StudySessionItemResponse(ApiModel):
    id: int
    learning_path_id: int
    topic: str
    pre_test_score: float | None
    post_test_score: float | None
    started_at: str
    completed_at: str | None
    improvement: float | None


class StudySessionListResponse(ApiModel):
    learning_path_id: int
    sessions: list[StudySessionItemResponse]


class StudySessionResponse(ApiModel):
    session: StudySessionItemResponse


class StudySessionCompletionResponse(ApiModel):
    """The completed session, carrying the scores the server just computed.

    The scores are returned rather than echoed back from the request because
    the client never had them: they are the mean of the session's own graded
    attempts.
    """

    session_id: int
    completed: bool
    session: StudySessionItemResponse


class StudyPhaseAttemptCounts(ApiModel):
    """How many attempts the session holds in each phase of the cycle."""

    pre_test: int
    practice: int
    post_test: int


class StudySessionSummaryResponse(ApiModel):
    """Server-computed close of the cycle: what was predicted against what happened.

    ``band`` is the calibration judgement; the sentence that goes with it is
    the study surface's to write, in the learner's own language.
    """

    session: StudySessionItemResponse
    attempts: StudyPhaseAttemptCounts
    practice_score: float | None
    predicted: float | None
    measured: float | None
    calibration_delta: float | None
    band: CalibrationBand
    legacy_scored: bool


class StudyFlashcardItemResponse(ApiModel):
    id: int
    learning_path_id: int
    topic: str
    front: str
    back: str
    source: StudyFlashcardSource
    created_at: str
    provenance: Provenance


class StudyFlashcardResponse(ApiModel):
    flashcard: StudyFlashcardItemResponse


class StudyPredictionItemResponse(ApiModel):
    learning_path_id: int
    topic: str
    predicted: float
    rated_at: str


class StudyPredictionResponse(ApiModel):
    prediction: StudyPredictionItemResponse


class StudySelfExplanationItemResponse(ApiModel):
    id: int
    flashcard_id: int
    student_explanation: str
    scaffold_level: int
    created_at: str


class StudySelfExplanationResponse(ApiModel):
    self_explanation: StudySelfExplanationItemResponse


class StudyReflectionItemResponse(ApiModel):
    id: int
    session_id: int
    learning_path_id: int
    prompt: str
    reflection_text: str
    created_at: str


class StudyReflectionResponse(ApiModel):
    reflection: StudyReflectionItemResponse


class StudyQuestionListResponse(ApiModel):
    """Generated questions plus the language they were generated in."""

    learning_path_id: int
    topic: str
    content_language: ContentLanguage
    questions: list[Question]


class StudySessionQuestionListResponse(ApiModel):
    """A session's persisted question set, in generation order."""

    session_id: int
    learning_path_id: int
    questions: list[Question]


class StudyAttemptItemResponse(ApiModel):
    id: int
    learning_path_id: int
    session_id: int | None
    question_id: str
    answer_text: str
    confidence: int | None
    self_rating: int | None
    score: float | None
    phase: StudyAttemptPhase
    submitted_at: str


class StudyAttemptResponse(ApiModel):
    attempt: StudyAttemptItemResponse
