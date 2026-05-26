"""Lecture API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel


class LectureModuleResponse(ApiModel):
    module_id: int
    series_id: str
    course_name: str


class LectureModulesResponse(ApiModel):
    modules: list[LectureModuleResponse]


class LectureEpisodeResponse(ApiModel):
    episode_id: str
    title: str
    download_status: str
    skip_reason: str | None
    transcription_status: str | None
    index_status: str | None
    lecture_number: int | None
    missed_at: str | None


class LectureEpisodesResponse(ApiModel):
    module_id: int
    episodes: list[LectureEpisodeResponse]


class LecturePipelineStatusResponse(ApiModel):
    module_id: int
    episodes: list[LectureEpisodeResponse]


class DiscoveredLectureModuleResponse(ApiModel):
    course_shortname: str
    course_fullname: str
    module_id: int
    module_name: str
    episode_count: int


class LectureDiscoveryResponse(ApiModel):
    modules: list[DiscoveredLectureModuleResponse]
