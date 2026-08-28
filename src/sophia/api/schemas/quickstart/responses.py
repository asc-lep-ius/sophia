"""Quickstart API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel
from sophia.api.schemas.deadlines import DeadlineResponse  # noqa: TC001
from sophia.api.schemas.topics import TopicOrigin  # noqa: TC001


class QuickstartLearningPathResponse(ApiModel):
    id: int
    title: str
    short_title: str
    url: str | None


class QuickstartTopicResponse(ApiModel):
    topic: str
    learning_path_id: int
    source: TopicOrigin
    frequency: int


class QuickstartOverviewResponse(ApiModel):
    learning_path_id: int | None
    learning_paths: list[QuickstartLearningPathResponse]
    topics: list[QuickstartTopicResponse]
    nearest_deadline: DeadlineResponse | None
    completed_session_count: int


class QuickstartConfidenceResponse(ApiModel):
    learning_path_id: int
    saved_count: int


class QuickstartManualTopicsResponse(ApiModel):
    learning_path_id: int
    topics: list[QuickstartTopicResponse]


class QuickstartSessionCountResponse(ApiModel):
    learning_path_id: int | None
    completed_session_count: int
