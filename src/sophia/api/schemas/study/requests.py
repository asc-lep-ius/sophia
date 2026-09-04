"""Study API request DTOs."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from sophia.api.schemas.common import ApiModel


class StudyFlashcardSource(StrEnum):
    """Where a flashcard came from, in source-agnostic terms."""

    STUDY = "study"
    TRANSCRIPT = "transcript"
    MANUAL = "manual"


class StudyAttemptPhase(StrEnum):
    """Which part of the equilibration cycle an attempt belongs to."""

    PRE_TEST = "pre_test"
    PRACTICE = "practice"
    POST_TEST = "post_test"


class StudySessionStartRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)


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

    @model_validator(mode="after")
    def _session_and_request_id_travel_together(self) -> Self:
        if (self.session_id is None) != (self.request_id is None):
            msg = "session_id and request_id must be given together, or not at all"
            raise ValueError(msg)
        return self


class StudyQuestionRequest(ApiModel):
    """Generate a batch of questions, optionally bound to a live session.

    Passing ``session_id`` is what makes the batch readable back through
    ``listStudySessionQuestions``; without it the questions belong to the
    learning path alone, as they did before the study surface existed.
    """

    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    count: int = Field(default=3, ge=1, le=10)
    session_id: int | None = Field(default=None, gt=0)


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

    ``phase`` says where in the cycle the attempt was made. The client chooses
    it, but it cannot forge a better outcome by doing so: the phase decides
    which mean an attempt is averaged into, never what the attempt scores.
    """

    learning_path_id: int = Field(gt=0)
    session_id: int = Field(gt=0)
    question_id: str = Field(min_length=1, max_length=128)
    answer_text: str = Field(min_length=1)
    confidence: int | None = Field(default=None, ge=1, le=5)
    self_rating: int = Field(ge=1, le=4)
    request_id: str = Field(min_length=1, max_length=128)
    phase: StudyAttemptPhase = StudyAttemptPhase.PRACTICE


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
