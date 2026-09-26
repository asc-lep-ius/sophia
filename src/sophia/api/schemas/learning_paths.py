"""Learning path listing and selection transport schemas."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class LearningPathResponse(ApiModel):
    id: int
    title: str
    short_title: str
    url: str | None


class LearningPathListResponse(ApiModel):
    # The session's selection, null until there is one. Required, so a client
    # has to handle the unselected state rather than read a missing key.
    learning_path_id: int | None
    learning_paths: list[LearningPathResponse]


class LearningPathSelectionRequest(ApiModel):
    learning_path_id: int = Field(gt=0)


class LearningPathSelectionResponse(ApiModel):
    learning_path_id: int
