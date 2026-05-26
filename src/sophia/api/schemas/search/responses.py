"""Search API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel


class LectureSearchResultResponse(ApiModel):
    episode_id: str
    title: str
    chunk_text: str
    start_time: float
    end_time: float
    score: float
    source: str


class LectureSearchResponse(ApiModel):
    results: list[LectureSearchResultResponse]
