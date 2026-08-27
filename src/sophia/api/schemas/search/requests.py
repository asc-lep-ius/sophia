"""Search API request DTOs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class ContentSearchSourceFilter(StrEnum):
    """Kind of indexed content a search request is restricted to."""

    ALL = "all"
    TRANSCRIPT = "transcript"
    DOCUMENT = "document"


class ContentSearchRequest(ApiModel):
    content_source_id: int = Field(gt=0)
    query: str = Field(min_length=1)
    n_results: int = Field(default=5, ge=1, le=25)
    source_filter: ContentSearchSourceFilter | None = None
    learning_path_id: int | None = Field(default=None, gt=0)
    missed_only: bool = False
