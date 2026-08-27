"""Authenticated content source and content item catalog routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, status

from sophia.api.deps import current_session_record, get_app_container, require_csrf
from sophia.api.schemas.content_sources import (
    ContentItemListResponse,
    ContentItemResponse,
    ContentSourceDiscoveryResponse,
    ContentSourceIngestionStatusResponse,
    ContentSourceListResponse,
    ContentSourceResponse,
    DiscoveredContentSourceResponse,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.services.hermes_catalog import discover_lecture_modules, get_lecture_modules
from sophia.services.hermes_manage import EpisodeStatus, get_pipeline_status

router = APIRouter(tags=["content-sources"])

ContentSourceIdPath = Annotated[int, Path(gt=0)]


@router.get(
    "/content-sources",
    response_model=ContentSourceListResponse,
    operation_id="listContentSources",
)
async def list_content_sources(request: Request) -> ContentSourceListResponse:
    await current_session_record(request)
    app = get_app_container(request)
    modules = await get_lecture_modules(app.db)
    return ContentSourceListResponse(
        sources=[
            ContentSourceResponse(
                id=module.module_id,
                external_ref=module.series_id,
                title=module.course_name,
            )
            for module in modules
        ],
    )


@router.post(
    "/content-sources/discover",
    response_model=ContentSourceDiscoveryResponse,
    operation_id="discoverContentSources",
)
async def discover_content_sources(request: Request) -> ContentSourceDiscoveryResponse:
    await require_csrf(request)
    modules = await discover_lecture_modules(get_app_container(request))
    return ContentSourceDiscoveryResponse(
        sources=[
            DiscoveredContentSourceResponse(
                id=module.module_id,
                title=module.module_name,
                learning_path_title=module.course_fullname,
                learning_path_short_title=module.course_shortname,
                content_item_count=module.episode_count,
            )
            for module in modules
        ],
    )


@router.get(
    "/content-sources/{content_source_id}/content-items",
    response_model=ContentItemListResponse,
    operation_id="listContentItems",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_content_items(
    content_source_id: ContentSourceIdPath,
    request: Request,
) -> ContentItemListResponse:
    items = await _content_item_rows(content_source_id, request)
    return ContentItemListResponse(
        content_source_id=content_source_id,
        items=[_content_item_response(item) for item in items],
    )


@router.get(
    "/content-sources/{content_source_id}/ingestion-status",
    response_model=ContentSourceIngestionStatusResponse,
    operation_id="readContentSourceIngestionStatus",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def read_content_source_ingestion_status(
    content_source_id: ContentSourceIdPath,
    request: Request,
) -> ContentSourceIngestionStatusResponse:
    items = await _content_item_rows(content_source_id, request)
    return ContentSourceIngestionStatusResponse(
        content_source_id=content_source_id,
        items=[_content_item_response(item) for item in items],
    )


async def _content_item_rows(content_source_id: int, request: Request) -> list[EpisodeStatus]:
    await current_session_record(request)
    app = get_app_container(request)
    episodes = await get_pipeline_status(app.db, content_source_id)
    if not episodes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return episodes


def _content_item_response(episode: EpisodeStatus) -> ContentItemResponse:
    return ContentItemResponse(
        id=episode.episode_id,
        title=episode.title,
        download_status=episode.download_status,
        skip_reason=episode.skip_reason,
        transcription_status=episode.transcription_status,
        index_status=episode.index_status,
        sequence_number=episode.lecture_number,
        missed_at=episode.missed_at,
    )
