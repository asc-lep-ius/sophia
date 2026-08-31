"""Authenticated learner-process event ingestion.

The trace these events form is what the engagement policy is judged against, so
ingestion refuses to take the learner's identity or learning path from the body:
both come from the session. Batch size is bounded by the request schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, status

from sophia.api.deps import (
    get_settings,
    request_session,
    require_csrf_learning_path_scope,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.learning_events import (
    LearningEventBatchRequest,
    LearningEventBatchResponse,
)
from sophia.api.transactions import TransactionalRoute
from sophia.domain.learning import LearningEvent
from sophia.domain.learning import LearningEventType as DomainLearningEventType
from sophia.services.learning_events import ingest_events

if TYPE_CHECKING:
    from sophia.api.schemas.learning_events import LearningEventInput

router = APIRouter(tags=["events"], route_class=TransactionalRoute)


@router.post(
    "/events/batch",
    response_model=LearningEventBatchResponse,
    operation_id="ingestLearningEvents",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def ingest_learning_event_batch(
    payload: LearningEventBatchRequest,
    request: Request,
) -> LearningEventBatchResponse:
    session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    settings = get_settings(request)
    result = await ingest_events(
        await request_session(request),
        [
            _domain_event(event, payload.learning_path_id, session.user.id)
            for event in payload.events
        ],
        max_future_skew_seconds=settings.learning_event_max_future_skew_seconds,
    )
    return LearningEventBatchResponse(
        learning_path_id=payload.learning_path_id,
        accepted=result.accepted,
        duplicate=result.duplicate,
    )


def _domain_event(
    event: LearningEventInput,
    learning_path_id: int,
    user_id: str,
) -> LearningEvent:
    return LearningEvent(
        event_id=event.event_id,
        course_id=learning_path_id,
        user_id=user_id,
        event_type=DomainLearningEventType(event.event_type.value),
        occurred_at=event.occurred_at,
        session_id=event.session_id,
        question_id=event.question_id,
        payload=dict(event.payload),
    )
