"""Learning-process primitives: provenance, events, engagement policy, questions.

These are the pedagogy and integrity foundations the study surface depends on.
They live apart from ``sophia.domain.models`` because they describe the *process*
of learning rather than the catalog of things a learner works with.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — Pydantic needs runtime access
from enum import StrEnum

from pydantic import BaseModel, Field

type EventPayloadValue = str | int | float | bool | None


class StoredContentOrigin(StrEnum):
    """Concrete system a piece of content was ingested from.

    Persisted verbatim so the audit trail keeps the vendor name. The public API
    deliberately maps this onto a source-agnostic discriminator instead of
    leaking the vendor into the generated client.
    """

    TUWEL = "tuwel"


class ProvenanceAgent(StrEnum):
    """Who produced a piece of content."""

    LEARNER = "learner"
    MODEL = "model"


class ContentKind(StrEnum):
    """What kind of content a provenance or translation record describes."""

    FLASHCARD = "flashcard"
    QUESTION = "question"
    SUMMARY = "summary"


class ContentLanguage(StrEnum):
    """Language a piece of learning content is authored in.

    Distinct from the user's UI locale on purpose: content follows the exam
    language of the learning path, never the language of the chrome around it.
    """

    DE = "de"
    EN = "en"


class QuestionKind(StrEnum):
    """Response format of a question, which decides how it is rendered."""

    OPEN_RESPONSE = "open_response"
    MULTIPLE_CHOICE = "multiple_choice"
    CLOZE = "cloze"


class LearningEventType(StrEnum):
    """Traceable steps of the predict → act → reflect cycle."""

    PROMPT_SHOWN = "prompt_shown"
    PREDICTION_MADE = "prediction_made"
    ELABORATION_WRITTEN = "elaboration_written"
    HINT_REQUESTED = "hint_requested"
    ANSWER_REVEALED = "answer_revealed"
    SELF_EXPLANATION_WRITTEN = "self_explanation_written"
    REFLECTION_WRITTEN = "reflection_written"


class SourceSpan(BaseModel, frozen=True):
    """A located region of ingested material backing a piece of content.

    Character offsets locate text material; millisecond offsets locate
    time-based material. Both are optional because a span may be known only
    coarsely, as a whole content item.
    """

    content_item_id: str
    start_char: int | None = None
    end_char: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    excerpt: str | None = None


class ContentProvenance(BaseModel, frozen=True):
    """Where a piece of generated content came from and whether it was checked."""

    content_kind: ContentKind
    content_id: str
    course_id: int
    origin: StoredContentOrigin
    generated_by: ProvenanceAgent
    generator_ref: str | None = None
    generated_at: str = ""
    verified_by: str | None = None
    verified_at: str | None = None
    source_spans: tuple[SourceSpan, ...] = ()


class ContentTranslation(BaseModel, frozen=True):
    """A translated rendering of a content item.

    Reserved shape. Nothing writes these until the translation pipeline ships;
    the API and the table exist so that adding it later is additive.
    """

    content_kind: ContentKind
    content_id: str
    language: ContentLanguage
    translated_at: str


class LearningEvent(BaseModel, frozen=True):
    """One recorded step of a learner's process, used for policy and triage."""

    event_id: str
    course_id: int
    user_id: str
    event_type: LearningEventType
    occurred_at: datetime
    session_id: int | None = None
    question_id: str | None = None
    payload: dict[str, EventPayloadValue] = Field(default_factory=dict)


class ElaborationPolicy(BaseModel, frozen=True):
    """Requires the learner to have elaborated before an answer is accepted."""

    required_event_types: tuple[LearningEventType, ...]
    min_elaboration_chars: int
    min_prompt_dwell_ms: int


class LearningPathSettings(BaseModel, frozen=True):
    """Per-learning-path pedagogy settings resolved from the upstream source."""

    course_id: int
    exam_language: ContentLanguage
    content_origin: StoredContentOrigin


class QuestionOption(BaseModel, frozen=True):
    """One selectable option of a multiple-choice question."""

    id: str
    text: str


class ClozeSegment(BaseModel, frozen=True):
    """One segment of a cloze question; a blank segment carries no text."""

    text: str | None = None
    blank: bool = False


class GeneratedQuestion(BaseModel, frozen=True):
    """A question produced for a learner, with the policy that gates answering it."""

    id: str
    course_id: int
    topic: str
    kind: QuestionKind
    prompt: str
    difficulty: str
    content_language: ContentLanguage
    options: tuple[QuestionOption, ...] = ()
    segments: tuple[ClozeSegment, ...] = ()
    elaboration_policy: ElaborationPolicy | None = None


class QuestionAttempt(BaseModel, frozen=True):
    """A learner's submitted answer to a generated question."""

    id: int
    course_id: int
    question_id: str
    user_id: str
    answer_text: str
    confidence: int | None
    submitted_at: str
