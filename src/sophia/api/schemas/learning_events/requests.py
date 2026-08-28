"""Learning event ingestion request DTOs."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — Pydantic needs runtime access

from pydantic import Field

from sophia.api.schemas.common import ApiModel, JsonPrimitive
from sophia.api.schemas.engagement import LearningEventType  # noqa: TC001

MAX_LEARNING_EVENT_BATCH_SIZE = 100
"""Contract limit on one batch, so a flooding client is rejected at the edge."""

MAX_LEARNING_EVENT_PAYLOAD_KEYS = 20


class LearningEventInput(ApiModel):
    """One learner-process event submitted for ingestion.

    ``event_id`` is the client's idempotency key: re-sending a batch after a
    timeout records nothing twice. The owning user and learning path are taken
    from the session, never from the body, so a client cannot attribute events
    to somebody else.
    """

    event_id: str = Field(min_length=1, max_length=128)
    event_type: LearningEventType
    occurred_at: datetime
    session_id: int | None = Field(default=None, gt=0)
    question_id: str | None = Field(default=None, min_length=1, max_length=128)
    payload: dict[str, JsonPrimitive] = Field(
        default_factory=dict,
        max_length=MAX_LEARNING_EVENT_PAYLOAD_KEYS,
    )


class LearningEventBatchRequest(ApiModel):
    """A bounded batch of learner-process events for one learning path."""

    learning_path_id: int = Field(gt=0)
    events: list[LearningEventInput] = Field(
        min_length=1,
        max_length=MAX_LEARNING_EVENT_BATCH_SIZE,
    )
