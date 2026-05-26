"""Search API request DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class LectureSearchRequest(ApiModel):
    module_id: int = Field(gt=0)
    query: str = Field(min_length=1)
    n_results: int = Field(default=5, ge=1, le=25)
    source_filter: Literal["all", "lecture", "pdf"] | None = None
    course_id: int | None = Field(default=None, gt=0)
    missed_only: bool = False
