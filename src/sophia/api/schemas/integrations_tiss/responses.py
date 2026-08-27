"""TISS integration API response DTOs.

Course numbers, semesters, and group ids are TISS vocabulary on purpose: this
resource is namespaced under ``/api/integrations/tiss`` precisely so the core
contract does not have to carry them.
"""

from __future__ import annotations

from enum import StrEnum

from sophia.api.schemas.common import ApiModel


class TissConnectionState(StrEnum):
    """State of the learner's stored TISS credentials."""

    CONNECTED = "connected"
    SESSION_MISSING = "session_missing"
    SESSION_EXPIRED = "session_expired"


class TissFavoriteResponse(ApiModel):
    course_number: str
    title: str
    course_type: str
    semester: str
    hours: float
    ects: float
    lva_registered: bool
    group_registered: bool
    exam_registered: bool


class TissFavoriteListResponse(ApiModel):
    connection: TissConnectionState
    semester: str
    favorites: list[TissFavoriteResponse]


class TissRegistrationGroupResponse(ApiModel):
    group_id: str
    name: str
    day: str
    time_start: str
    time_end: str
    location: str
    capacity: int
    enrolled: int
    status: str


class TissRegistrationGroupListResponse(ApiModel):
    connection: TissConnectionState
    course_number: str
    semester: str
    groups: list[TissRegistrationGroupResponse]


class TissRegistrationTargetResponse(ApiModel):
    course_number: str
    semester: str
    registration_type: str
    title: str
    registration_start: str | None
    registration_end: str | None
    status: str
    groups: list[TissRegistrationGroupResponse]


class TissRegistrationStatusResponse(ApiModel):
    connection: TissConnectionState
    course_number: str
    semester: str
    target: TissRegistrationTargetResponse | None


class TissRegistrationAttemptResultResponse(ApiModel):
    course_number: str
    registration_type: str
    success: bool
    group_name: str
    message: str
    attempted_at: str


class TissRegistrationAttemptResponse(ApiModel):
    connection: TissConnectionState
    course_number: str
    semester: str
    result: TissRegistrationAttemptResultResponse | None


class TissExamDateResponse(ApiModel):
    exam_id: str
    course_number: str
    title: str
    date_start: str | None
    date_end: str | None
    registration_start: str | None
    registration_end: str | None
    mode: str


class TissExamDateListResponse(ApiModel):
    course_number: str
    exams: list[TissExamDateResponse]
