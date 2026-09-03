"""Study API request DTOs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class StudyFlashcardSource(StrEnum):
    """Where a flashcard came from, in source-agnostic terms."""

    STUDY = "study"
    TRANSCRIPT = "transcript"
    MANUAL = "manual"


class StudySessionStartRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)


class StudySessionCompleteRequest(ApiModel):
    pre_test_score: float = Field(ge=0.0, le=1.0)
    post_test_score: float = Field(ge=0.0, le=1.0)


class StudyFlashcardRequest(ApiModel):
    """Save a flashcard.

    ``session_id`` and ``request_id`` are optional: a flashcard saved outside a
    live study session (there is no session to be idempotent within) omits
    both and is saved unconditionally, as before. Both must be given together
    to opt into the idempotent, session-scoped path.
    """

    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    front: str = Field(min_length=1)
    back: str = Field(min_length=1)
    source: StudyFlashcardSource = StudyFlashcardSource.STUDY
    session_id: int | None = Field(default=None, gt=0)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class StudyQuestionRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    count: int = Field(default=3, ge=1, le=10)


class StudyAttemptRequest(ApiModel):
    """A learner's answer to a previously generated question, self-graded.

    The question is referenced by id rather than echoed back, so the engagement
    policy the server enforces is the one it issued, not one the client claims.

    ``self_rating`` is the post-reveal Again/Hard/Good/Easy self-assessment the
    learner gives once they see the expected answer — the score is computed
    from that, not from ``answer_text`` alone, since nothing in the system
    stores an answer key to grade against. ``request_id`` is a client-generated
    idempotency key: retrying the same submission returns the original result
    rather than recording a second attempt.
    """

    learning_path_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    question_id: str = Field(min_length=1, max_length=128)
    answer_text: str = Field(min_length=1)
    confidence: int | None = Field(default=None, ge=1, le=5)
    self_rating: int = Field(ge=1, le=4)
    request_id: str = Field(min_length=1, max_length=128)


class StudyPredictionRequest(ApiModel):
    """A learner's pre-question confidence prediction for a topic, made during
    a live study session — idempotent on ``request_id``."""

    learning_path_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)
    request_id: str = Field(min_length=1, max_length=128)


class StudySelfExplanationRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    flashcard_id: int = Field(gt=0)
    student_explanation: str = Field(min_length=1)
    scaffold_level: int = Field(default=3, ge=0, le=3)
    request_id: str = Field(min_length=1, max_length=128)


class StudyReflectionRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    prompt: str = Field(min_length=1)
    reflection_text: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=128)
