"""Content source and content item API response DTOs."""

from __future__ import annotations

from enum import StrEnum

from sophia.api.schemas.common import ApiModel


class IngestionState(StrEnum):
    """Where an accepted upload sits in the processing that follows it.

    Kept apart from the service's own state enum in the same way the topic and
    content-language transports are: the wire contract is allowed to outlive
    whatever the pipeline calls its stages internally.
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    FAILED = "failed"
    READY = "ready"


class ContentSourceResponse(ApiModel):
    id: int
    external_ref: str
    title: str


class ContentSourceListResponse(ApiModel):
    sources: list[ContentSourceResponse]


class ContentItemResponse(ApiModel):
    id: str
    title: str
    download_status: str
    skip_reason: str | None
    transcription_status: str | None
    index_status: str | None
    sequence_number: int | None
    missed_at: str | None


class ContentItemListResponse(ApiModel):
    content_source_id: int
    items: list[ContentItemResponse]


class ContentSourceIngestionStatusResponse(ApiModel):
    content_source_id: int
    items: list[ContentItemResponse]


class DiscoveredContentSourceResponse(ApiModel):
    id: int
    title: str
    learning_path_title: str
    learning_path_short_title: str
    content_item_count: int


class ContentSourceDiscoveryResponse(ApiModel):
    sources: list[DiscoveredContentSourceResponse]


class ContentSourceUploadResponse(ApiModel):
    """An upload the ingestion boundary accepted and staged.

    ``state`` is part of the accept response rather than implied by it: the
    processing that follows an upload takes minutes, and a surface that cannot
    tell queued from ready has no honest thing to show in between.
    """

    id: str
    title: str
    media_type: str
    byte_size: int
    state: IngestionState
