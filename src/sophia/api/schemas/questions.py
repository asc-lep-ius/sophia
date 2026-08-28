"""Discriminated question union served to the study surface.

Variants discriminate on *response format*, because that is what actually
differs structurally and what decides how the surface renders a question. The
pedagogy axis rides along on every variant as ``difficulty``, and the
engagement policy varies per variant: only a free-response format can demand an
elaboration trace before it accepts an answer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from sophia.api.schemas.common import ApiModel
from sophia.api.schemas.content import ContentLanguage, ContentTranslation  # noqa: TC001
from sophia.api.schemas.engagement import ElaborationPolicy, NoEngagementPolicy
from sophia.api.schemas.provenance import Provenance  # noqa: TC001


class QuestionDifficulty(StrEnum):
    """Adaptive difficulty band a question was generated for."""

    CUED = "cued"
    EXPLAIN = "explain"
    TRANSFER = "transfer"


class QuestionOption(ApiModel):
    """One selectable option of a multiple-choice question."""

    id: str
    text: str


class ClozeSegment(ApiModel):
    """One segment of a cloze question; a blank segment carries no text."""

    text: str | None = None
    blank: bool = False


class QuestionBase(ApiModel):
    """Fields every question carries regardless of response format."""

    id: str
    topic: str
    difficulty: QuestionDifficulty
    content_language: ContentLanguage
    provenance: Provenance
    translations: list[ContentTranslation] = Field(default_factory=list[ContentTranslation])


class OpenResponseQuestion(QuestionBase):
    """Free-response question, the only format that can gate on elaboration."""

    kind: Literal["open_response"] = "open_response"
    prompt: str
    engagement_policy: ElaborationPolicy


class MultipleChoiceQuestion(QuestionBase):
    """Recognition question; ungated because selecting is not elaborating."""

    kind: Literal["multiple_choice"] = "multiple_choice"
    prompt: str
    options: list[QuestionOption]
    engagement_policy: NoEngagementPolicy = NoEngagementPolicy()


class ClozeQuestion(QuestionBase):
    """Fill-in-the-blank question, rendered from ordered segments."""

    kind: Literal["cloze"] = "cloze"
    segments: list[ClozeSegment]
    engagement_policy: NoEngagementPolicy = NoEngagementPolicy()


type Question = Annotated[
    OpenResponseQuestion | MultipleChoiceQuestion | ClozeQuestion,
    Field(discriminator="kind"),
]
