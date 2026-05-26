"""Authenticated Hermes lecture catalog routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, status

from sophia.api.deps import current_session_record, get_app_container, require_csrf
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.lectures import (
    DiscoveredLectureModuleResponse,
    LectureDiscoveryResponse,
    LectureEpisodeResponse,
    LectureEpisodesResponse,
    LectureModuleResponse,
    LectureModulesResponse,
    LecturePipelineStatusResponse,
)
from sophia.services.hermes_catalog import discover_lecture_modules, get_lecture_modules
from sophia.services.hermes_manage import EpisodeStatus, get_pipeline_status

router = APIRouter(tags=["lectures"])

ModuleIdPath = Annotated[int, Path(gt=0)]


@router.get(
    "/lectures/modules",
    response_model=LectureModulesResponse,
    operation_id="listLectureModules",
)
async def list_lecture_modules(request: Request) -> LectureModulesResponse:
    await current_session_record(request)
    app = get_app_container(request)
    modules = await get_lecture_modules(app.db)
    return LectureModulesResponse(
        modules=[
            LectureModuleResponse(
                module_id=module.module_id,
                series_id=module.series_id,
                course_name=module.course_name,
            )
            for module in modules
        ],
    )


@router.get(
    "/lectures/modules/{module_id}/episodes",
    response_model=LectureEpisodesResponse,
    operation_id="listLectureModuleEpisodes",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_lecture_module_episodes(
    module_id: ModuleIdPath,
    request: Request,
) -> LectureEpisodesResponse:
    episodes = await _module_episode_rows(module_id, request)
    return LectureEpisodesResponse(
        module_id=module_id,
        episodes=[_episode_response(episode) for episode in episodes],
    )


@router.get(
    "/lectures/modules/{module_id}/pipeline-status",
    response_model=LecturePipelineStatusResponse,
    operation_id="readLecturePipelineStatus",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def read_lecture_pipeline_status(
    module_id: ModuleIdPath,
    request: Request,
) -> LecturePipelineStatusResponse:
    episodes = await _module_episode_rows(module_id, request)
    return LecturePipelineStatusResponse(
        module_id=module_id,
        episodes=[_episode_response(episode) for episode in episodes],
    )


@router.post(
    "/lectures/discover",
    response_model=LectureDiscoveryResponse,
    operation_id="discoverLectureModules",
)
async def discover_modules(request: Request) -> LectureDiscoveryResponse:
    await require_csrf(request)
    modules = await discover_lecture_modules(get_app_container(request))
    return LectureDiscoveryResponse(
        modules=[
            DiscoveredLectureModuleResponse(
                course_shortname=module.course_shortname,
                course_fullname=module.course_fullname,
                module_id=module.module_id,
                module_name=module.module_name,
                episode_count=module.episode_count,
            )
            for module in modules
        ],
    )


async def _module_episode_rows(module_id: int, request: Request) -> list[EpisodeStatus]:
    await current_session_record(request)
    app = get_app_container(request)
    episodes = await get_pipeline_status(app.db, module_id)
    if not episodes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return episodes


def _episode_response(episode: EpisodeStatus) -> LectureEpisodeResponse:
    return LectureEpisodeResponse(
        episode_id=episode.episode_id,
        title=episode.title,
        download_status=episode.download_status,
        skip_reason=episode.skip_reason,
        transcription_status=episode.transcription_status,
        index_status=episode.index_status,
        lecture_number=episode.lecture_number,
        missed_at=episode.missed_at,
    )
