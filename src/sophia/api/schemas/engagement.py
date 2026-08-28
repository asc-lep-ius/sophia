"""Engagement policy and learning-event vocabulary shared across study routes."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class LearningEventType(StrEnum):
    """Traceable steps of the predict → act → reflect cycle."""

    PROMPT_SHOWN = "prompt_shown"
    PREDICTION_MADE = "prediction_made"
    ELABORATION_WRITTEN = "elaboration_written"
    HINT_REQUESTED = "hint_requested"
    ANSWER_REVEALED = "answer_revealed"
    SELF_EXPLANATION_WRITTEN = "self_explanation_written"
    REFLECTION_WRITTEN = "reflection_written"


class ElaborationPolicy(ApiModel):
    """Answering is gated on a recorded elaboration trace.

    The client cannot satisfy this by asserting it complied: the server reads
    the learner's own ingested events and rejects the submission with 412 when
    the trace is missing.
    """

    kind: Literal["elaboration"] = "elaboration"
    required_event_types: list[LearningEventType]
    min_elaboration_chars: int = Field(ge=0)
    min_prompt_dwell_ms: int = Field(ge=0)


class NoEngagementPolicy(ApiModel):
    """Answering is ungated — recognition formats carry no elaboration demand."""

    kind: Literal["none"] = "none"
