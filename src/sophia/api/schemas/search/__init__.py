"""Search API transport schemas."""

from sophia.api.schemas.search.requests import LectureSearchRequest
from sophia.api.schemas.search.responses import LectureSearchResponse, LectureSearchResultResponse

__all__ = [
    "LectureSearchRequest",
    "LectureSearchResponse",
    "LectureSearchResultResponse",
]
