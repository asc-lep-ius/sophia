"""Quickstart API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.chronos import ChronosDeadlineResponse  # noqa: TC001
from sophia.api.schemas.common import ApiModel


class QuickstartCourseResponse(ApiModel):
    id: int
    fullname: str
    shortname: str
    url: str | None


class QuickstartTopicResponse(ApiModel):
    topic: str
    course_id: int
    source: str
    frequency: int


class QuickstartOverviewResponse(ApiModel):
    course_id: int | None
    courses: list[QuickstartCourseResponse]
    topics: list[QuickstartTopicResponse]
    nearest_deadline: ChronosDeadlineResponse | None
    completed_session_count: int


class QuickstartConfidenceResponse(ApiModel):
    course_id: int
    saved_count: int


class QuickstartManualTopicsResponse(ApiModel):
    course_id: int
    topics: list[QuickstartTopicResponse]


class QuickstartSessionCountResponse(ApiModel):
    course_id: int | None
    completed_session_count: int
