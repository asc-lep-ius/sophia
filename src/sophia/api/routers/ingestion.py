"""Processing a learning path's recordings from the browser (#128).

Process queues a job for the worker and subscribes the learning path, so new
recordings are processed on the next scan or overnight without another press.
Status is read back from the queue, so it survives a reload and a closed tab.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Path, Request, status
from sqlalchemy import select

from sophia.api.deps import (
    get_settings,
    request_session,
    require_csrf_learning_path_scope,
    require_learning_path_scope,
)
from sophia.api.schemas.content_sources import IngestionState
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.ingestion import (
    IngestionJobResponse,
    IngestionSettingsRequest,
    IngestionSettingsResponse,
    IngestionSourceResponse,
    IngestionStatusResponse,
    IngestionWorkerResponse,
)
from sophia.api.transactions import TransactionalRoute
from sophia.infra.schema import lecture_modules
from sophia.services.ingestion_jobs import (
    COMPLETED,
    FAILED,
    RUNNING,
    latest_job,
    request_ingestion,
    worker_availability,
)
from sophia.services.ingestion_settings import (
    IngestionSettings,
    get_ingestion_settings,
    save_ingestion_settings,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.services.ingestion_jobs import IngestionJob

router = APIRouter(tags=["ingestion"], route_class=TransactionalRoute)

LearningPathIdPath = Annotated[int, Path(gt=0)]

_STATE_BY_STATUS = {
    RUNNING: IngestionState.PROCESSING,
    COMPLETED: IngestionState.READY,
    FAILED: IngestionState.FAILED,
}


@router.get(
    "/learning-paths/{learning_path_id}/ingestion",
    response_model=IngestionStatusResponse,
    operation_id="readIngestionStatus",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorEnvelope}},
)
async def read_ingestion_status(
    learning_path_id: LearningPathIdPath,
    request: Request,
) -> IngestionStatusResponse:
    await require_learning_path_scope(request, learning_path_id)
    db = await request_session(request)
    stale_after = get_settings(request).ingestion_worker_stale_seconds
    availability = await worker_availability(db, stale_after_s=stale_after)
    job = await latest_job(db, learning_path_id)
    return IngestionStatusResponse(
        learning_path_id=learning_path_id,
        settings=_settings_response(await get_ingestion_settings(db, learning_path_id)),
        worker=IngestionWorkerResponse(
            available=availability.available,
            reason=availability.reason,
            gpu_name=availability.gpu_name,
        ),
        job=None if job is None else _job_response(job),
        sources=await _sources(db, learning_path_id),
    )


@router.post(
    "/learning-paths/{learning_path_id}/ingestion",
    response_model=IngestionJobResponse,
    operation_id="startIngestion",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorEnvelope},
        status.HTTP_409_CONFLICT: {"model": ErrorEnvelope},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorEnvelope},
    },
)
async def start_ingestion(
    learning_path_id: LearningPathIdPath,
    request: Request,
) -> IngestionJobResponse:
    """Queue processing of every recording the learning path owns, and follow it.

    409 when a job is already queued or running for it; 503, with the reason,
    when no worker can process here. The first Process subscribes the path:
    from then on new recordings are processed without another press.
    """
    await require_csrf_learning_path_scope(request, learning_path_id)
    db = await request_session(request)
    stale_after = get_settings(request).ingestion_worker_stale_seconds
    job = await request_ingestion(db, learning_path_id, stale_after_s=stale_after)
    current = await get_ingestion_settings(db, learning_path_id)
    if not current.subscribed:
        await save_ingestion_settings(
            db,
            IngestionSettings(
                course_id=learning_path_id,
                subscribed=True,
                transcription_language=current.transcription_language,
            ),
        )
    return _job_response(job)


@router.put(
    "/learning-paths/{learning_path_id}/ingestion/settings",
    response_model=IngestionSettingsResponse,
    operation_id="saveIngestionSettings",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def save_ingestion_settings_route(
    learning_path_id: LearningPathIdPath,
    payload: IngestionSettingsRequest,
    request: Request,
) -> IngestionSettingsResponse:
    """Stop or resume following the learning path, and set its transcription language."""
    await require_csrf_learning_path_scope(request, learning_path_id)
    saved = await save_ingestion_settings(
        await request_session(request),
        IngestionSettings(
            course_id=learning_path_id,
            subscribed=payload.subscribed,
            transcription_language=payload.transcription_language,
        ),
    )
    return _settings_response(saved)


async def _sources(db: AsyncSession, learning_path_id: int) -> list[IngestionSourceResponse]:
    rows = (
        await db.execute(
            select(lecture_modules.c.module_id, lecture_modules.c.course_name)
            .where(lecture_modules.c.course_id == str(learning_path_id))
            .order_by(lecture_modules.c.module_id)
        )
    ).all()
    return [IngestionSourceResponse(id=row.module_id, title=row.course_name) for row in rows]


def _settings_response(settings: IngestionSettings) -> IngestionSettingsResponse:
    return IngestionSettingsResponse(
        learning_path_id=settings.course_id,
        subscribed=settings.subscribed,
        transcription_language=settings.transcription_language,
    )


def _job_response(job: IngestionJob) -> IngestionJobResponse:
    return IngestionJobResponse(
        id=job.id,
        learning_path_id=job.course_id,
        state=_STATE_BY_STATUS.get(job.status, IngestionState.QUEUED),
        requested_by=job.requested_by,
        stage=job.stage,
        content_source_id=job.module_id,
        error=job.error,
        requested_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )
