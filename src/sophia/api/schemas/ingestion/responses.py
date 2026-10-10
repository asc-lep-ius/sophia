"""Processing API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel
from sophia.api.schemas.content_sources import (  # noqa: TC001 — Pydantic resolves it at runtime
    IngestionState,
)


class IngestionWorkerResponse(ApiModel):
    """Whether processing can start here, and if not, the reason shown as the refusal."""

    available: bool
    reason: str
    gpu_name: str


class IngestionJobResponse(ApiModel):
    id: int
    learning_path_id: int
    state: IngestionState
    requested_by: str
    # "semester": the recordings dated within the learning path's own semester;
    # "older": the one-off run over the rest.
    scope: str
    stage: str | None
    content_source_id: int | None
    error: str | None
    requested_at: str
    started_at: str | None
    finished_at: str | None


class IngestionSettingsResponse(ApiModel):
    learning_path_id: int
    subscribed: bool
    transcription_language: str | None


class IngestionSourceResponse(ApiModel):
    """A content source the learning path owns, whose items processing covers."""

    id: int
    title: str


class IngestionStatusResponse(ApiModel):
    learning_path_id: int
    settings: IngestionSettingsResponse
    worker: IngestionWorkerResponse
    # The job in flight, else the last one, else null when nothing was ever started.
    job: IngestionJobResponse | None
    sources: list[IngestionSourceResponse]
    # Recordings from other semesters that are not processed yet: what
    # "Process older recordings too" would cover, shown only while non-zero.
    older_recordings_pending: int
