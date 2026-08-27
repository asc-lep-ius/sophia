"""Authenticated content search routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, status

from sophia.api.deps import get_app_container, require_effective_course_id
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.search import (
    ContentSearchRequest,
    ContentSearchResponse,
    ContentSearchResultResponse,
    ContentSearchSourceFilter,
)
from sophia.services.hermes_index import search_lectures

if TYPE_CHECKING:
    from sophia.domain.models import LectureSearchResult

router = APIRouter(tags=["search"])

# The index stores TU Wien source tags; the public contract stays content-agnostic.
_INDEX_FILTER_BY_API_FILTER = {
    ContentSearchSourceFilter.ALL: "all",
    ContentSearchSourceFilter.TRANSCRIPT: "lecture",
    ContentSearchSourceFilter.DOCUMENT: "pdf",
}
_API_SOURCE_BY_INDEX_SOURCE = {"lecture": "transcript", "pdf": "document"}


@router.post(
    "/search",
    response_model=ContentSearchResponse,
    operation_id="searchContent",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def search_content(
    payload: ContentSearchRequest,
    request: Request,
) -> ContentSearchResponse:
    effective_learning_path_id = await require_effective_course_id(
        request,
        payload.learning_path_id,
    )
    # Content source ownership is not persisted yet, so this keeps the pre-existing
    # scope equality check rather than relaxing it. See #103.
    if payload.content_source_id != effective_learning_path_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    results = await search_lectures(
        get_app_container(request),
        payload.content_source_id,
        payload.query,
        n_results=payload.n_results,
        source_filter=_index_source_filter(payload.source_filter),
        course_id=effective_learning_path_id,
        missed_only=payload.missed_only,
    )
    return ContentSearchResponse(results=[_search_result_response(result) for result in results])


def _index_source_filter(source_filter: ContentSearchSourceFilter | None) -> str | None:
    if source_filter is None:
        return None
    return _INDEX_FILTER_BY_API_FILTER[source_filter]


def _search_result_response(result: LectureSearchResult) -> ContentSearchResultResponse:
    return ContentSearchResultResponse(
        content_item_id=result.episode_id,
        title=result.title,
        chunk_text=result.chunk_text,
        start_time=result.start_time,
        end_time=result.end_time,
        score=result.score,
        source=_API_SOURCE_BY_INDEX_SOURCE.get(result.source, result.source),
    )
