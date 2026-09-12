"""Authenticated content source and content item catalog routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Path, Request, status

from sophia.api.deps import (
    current_session_record,
    get_app_container,
    get_settings,
    request_session,
    require_csrf,
)
from sophia.api.schemas.content_sources import (
    ContentItemListResponse,
    ContentItemResponse,
    ContentSourceDiscoveryResponse,
    ContentSourceIngestionStatusResponse,
    ContentSourceListResponse,
    ContentSourceResponse,
    ContentSourceUploadForm,
    ContentSourceUploadResponse,
    DiscoveredContentSourceResponse,
    IngestionState,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.transactions import TransactionalRoute
from sophia.services.content_uploads import stage_upload
from sophia.services.hermes_catalog import discover_lecture_modules, get_lecture_modules
from sophia.services.hermes_manage import EpisodeStatus, get_pipeline_status

router = APIRouter(tags=["content-sources"], route_class=TransactionalRoute)

ContentSourceIdPath = Annotated[int, Path(gt=0)]
UploadBody = Annotated[ContentSourceUploadForm, Form(media_type="multipart/form-data")]


@router.get(
    "/content-sources",
    response_model=ContentSourceListResponse,
    operation_id="listContentSources",
)
async def list_content_sources(request: Request) -> ContentSourceListResponse:
    await current_session_record(request)
    modules = await get_lecture_modules(await request_session(request))
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
    modules = await discover_lecture_modules(
        get_app_container(request),
        await request_session(request),
    )
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


@router.post(
    "/content-sources/uploads",
    response_model=ContentSourceUploadResponse,
    operation_id="createContentSourceUpload",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def create_content_source_upload(
    request: Request,
    upload: UploadBody,
) -> ContentSourceUploadResponse:
    """Accept one multipart upload, or say which check refused it.

    Deliberately reachable by a plain form post: the enhanced client adds
    progress and cancellation on top, but the surface a learner without
    JavaScript sees has to reach this same handler.
    """
    await require_csrf(request)
    settings = get_settings(request)
    staged = await stage_upload(
        title=upload.title,
        filename=upload.file.filename,
        read_chunk=upload.file.read,
        data_dir=settings.data_dir,
        max_bytes=settings.content_upload_max_bytes,
    )
    return ContentSourceUploadResponse(
        id=staged.upload_id,
        title=staged.title,
        media_type=staged.media_type,
        byte_size=staged.byte_size,
        state=IngestionState(staged.state.value),
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
    episodes = await get_pipeline_status(await request_session(request), content_source_id)
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
