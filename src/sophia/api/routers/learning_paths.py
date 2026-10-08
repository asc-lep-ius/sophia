"""The learner's learning paths, and the session's selection among them.

The selection lives on the session tenant and nowhere else: every scoped route
already reads it from there. Changing it moves nothing: sessions, decks and
review schedules stay under the learning path they were created in, and show
again when that one is selected.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, status

from sophia.api.deps import (
    current_session_record,
    get_app_container,
    require_csrf,
    save_session_record,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.learning_paths import (
    LearningPathListResponse,
    LearningPathResponse,
    LearningPathSelectionRequest,
    LearningPathSelectionResponse,
)
from sophia.api.sessions import utc_now_iso
from sophia.api.transactions import TransactionalRoute
from sophia.services.learning_paths import list_learning_paths

if TYPE_CHECKING:
    from sophia.api.sessions import SessionRecord
    from sophia.domain.models import Course

router = APIRouter(tags=["learning-paths"], route_class=TransactionalRoute)


@router.get(
    "/learning-paths",
    response_model=LearningPathListResponse,
    operation_id="listLearningPaths",
    responses={status.HTTP_502_BAD_GATEWAY: {"model": ErrorEnvelope}},
)
async def list_learning_paths_route(request: Request) -> LearningPathListResponse:
    session = await current_session_record(request)
    learning_paths = await list_learning_paths(get_app_container(request))
    return LearningPathListResponse(
        learning_path_id=_numeric_id(session.tenant.learning_path_id),
        learning_paths=[_learning_path_response(course) for course in learning_paths],
    )


@router.put(
    "/learning-paths/selection",
    response_model=LearningPathSelectionResponse,
    operation_id="selectLearningPath",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorEnvelope},
    },
)
async def select_learning_path(
    payload: LearningPathSelectionRequest,
    request: Request,
) -> LearningPathSelectionResponse:
    session = await require_csrf(request)
    # Only one of the learner's own: the tenant is what every scope check
    # compares against, so selecting an arbitrary id would widen them all.
    learning_paths = await list_learning_paths(get_app_container(request))
    if all(course.id != payload.learning_path_id for course in learning_paths):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    await save_session_record(request, _with_selection(session, payload.learning_path_id))
    return LearningPathSelectionResponse(learning_path_id=payload.learning_path_id)


def _with_selection(session: SessionRecord, learning_path_id: int) -> SessionRecord:
    tenant = replace(session.tenant, learning_path_id=str(learning_path_id))
    return replace(session, tenant=tenant, updated_at=utc_now_iso())


def _numeric_id(learning_path_id: str | None) -> int | None:
    if learning_path_id is None or not learning_path_id.isdigit():
        return None
    return int(learning_path_id)


def _learning_path_response(course: Course) -> LearningPathResponse:
    return LearningPathResponse(
        id=course.id,
        title=course.fullname,
        short_title=course.shortname,
        url=course.url,
    )
