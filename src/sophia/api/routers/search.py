"""Authenticated lecture search routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, status

from sophia.api.deps import get_app_container, require_effective_course_id
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.search import (
    LectureSearchRequest,
    LectureSearchResponse,
    LectureSearchResultResponse,
)
from sophia.services.hermes_index import search_lectures

if TYPE_CHECKING:
    from sophia.domain.models import LectureSearchResult

router = APIRouter(tags=["search"])


@router.post(
    "/search/lectures",
    response_model=LectureSearchResponse,
    operation_id="searchLectureContent",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def search_lecture_content(
    payload: LectureSearchRequest,
    request: Request,
) -> LectureSearchResponse:
    effective_course_id = await require_effective_course_id(request, payload.course_id)
    if payload.module_id != effective_course_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    results = await search_lectures(
        get_app_container(request),
        payload.module_id,
        payload.query,
        n_results=payload.n_results,
        source_filter=payload.source_filter,
        course_id=effective_course_id,
        missed_only=payload.missed_only,
    )
    return LectureSearchResponse(results=[_search_result_response(result) for result in results])


def _search_result_response(result: LectureSearchResult) -> LectureSearchResultResponse:
    return LectureSearchResultResponse(
        episode_id=result.episode_id,
        title=result.title,
        chunk_text=result.chunk_text,
        start_time=result.start_time,
        end_time=result.end_time,
        score=result.score,
        source=result.source,
    )
