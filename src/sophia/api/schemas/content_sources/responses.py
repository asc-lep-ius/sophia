"""Content source and content item API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel


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
