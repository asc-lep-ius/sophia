"""Authenticated TISS registration routes (Kairos).

Source-specific by design: TISS course numbers, semesters, and group ids are
irreducibly TU Wien concepts, so they live under /api/integrations/tiss rather
than in the content-agnostic core vocabulary.

Missing or expired TISS credentials are reported as a connection state on a
200 response, because a learner who never linked TISS is in a normal state,
not a failed request. Upstream faults raise TissError and map to 502.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Path, Query, Request, status

from sophia.api.deps import current_session_record, get_app_container, require_csrf
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.integrations_tiss import (
    TissConnectionState,
    TissExamDateListResponse,
    TissExamDateResponse,
    TissFavoriteListResponse,
    TissFavoriteResponse,
    TissRegistrationAttemptRequest,
    TissRegistrationAttemptResponse,
    TissRegistrationAttemptResultResponse,
    TissRegistrationGroupListResponse,
    TissRegistrationGroupResponse,
    TissRegistrationStatusResponse,
    TissRegistrationTargetResponse,
)
from sophia.domain.errors import TissError
from sophia.services.tiss_registration import (
    STATUS_AUTH_EXPIRED,
    STATUS_NO_SESSION,
    STATUS_SUCCESS,
    current_semester,
    get_exam_dates,
    get_favorites,
    get_groups,
    get_registration_status,
    register_course,
)

if TYPE_CHECKING:
    from sophia.domain.models import (
        FavoriteCourse,
        RegistrationGroup,
        RegistrationResult,
        RegistrationTarget,
        TissExamDate,
    )

router = APIRouter(tags=["integrations-tiss"])

# Course numbers are NNN.XXX, matching _FULLNAME_COURSE_PREFIX_RE in the TISS
# adapter, which already feeds alphanumeric numbers like 104.A32 upstream.
# Pinning the shape here keeps unencoded input out of the upstream request path.
COURSE_NUMBER_PATTERN = r"^\d{3}\.[A-Za-z0-9]{3}$"
CourseNumberPath = Annotated[str, Path(pattern=COURSE_NUMBER_PATTERN)]
SemesterQuery = Annotated[str | None, Query(min_length=1)]

_CONNECTION_STATES = {
    STATUS_NO_SESSION: TissConnectionState.SESSION_MISSING,
    STATUS_AUTH_EXPIRED: TissConnectionState.SESSION_EXPIRED,
    STATUS_SUCCESS: TissConnectionState.CONNECTED,
}
_UPSTREAM_FAILURE = "TISS registration is unavailable"


@router.get(
    "/integrations/tiss/registration/favorites",
    response_model=TissFavoriteListResponse,
    operation_id="listTissFavorites",
    responses={status.HTTP_502_BAD_GATEWAY: {"model": ErrorEnvelope}},
)
async def list_tiss_favorites(
    request: Request,
    semester: SemesterQuery = None,
) -> TissFavoriteListResponse:
    await current_session_record(request)
    effective_semester = semester or current_semester()
    result = await get_favorites(get_app_container(request), semester=effective_semester)
    return TissFavoriteListResponse(
        connection=_connection_state(result.status),
        semester=effective_semester,
        favorites=[_favorite_response(favorite) for favorite in result.favorites],
    )


@router.get(
    "/integrations/tiss/registration/targets/{course_number}",
    response_model=TissRegistrationStatusResponse,
    operation_id="getTissRegistrationTarget",
    responses={status.HTTP_502_BAD_GATEWAY: {"model": ErrorEnvelope}},
)
async def get_tiss_registration_target(
    course_number: CourseNumberPath,
    request: Request,
    semester: SemesterQuery = None,
) -> TissRegistrationStatusResponse:
    await current_session_record(request)
    effective_semester = semester or current_semester()
    result = await get_registration_status(
        get_app_container(request),
        course_number,
        effective_semester,
    )
    return TissRegistrationStatusResponse(
        connection=_connection_state(result.status),
        course_number=course_number,
        semester=effective_semester,
        target=_target_response(result.target) if result.target is not None else None,
    )


@router.get(
    "/integrations/tiss/registration/targets/{course_number}/groups",
    response_model=TissRegistrationGroupListResponse,
    operation_id="listTissRegistrationGroups",
    responses={status.HTTP_502_BAD_GATEWAY: {"model": ErrorEnvelope}},
)
async def list_tiss_registration_groups(
    course_number: CourseNumberPath,
    request: Request,
    semester: SemesterQuery = None,
) -> TissRegistrationGroupListResponse:
    await current_session_record(request)
    effective_semester = semester or current_semester()
    result = await get_groups(get_app_container(request), course_number, effective_semester)
    return TissRegistrationGroupListResponse(
        connection=_connection_state(result.status),
        course_number=course_number,
        semester=effective_semester,
        groups=[_group_response(group) for group in result.groups],
    )


@router.get(
    "/integrations/tiss/registration/targets/{course_number}/exam-dates",
    response_model=TissExamDateListResponse,
    operation_id="listTissExamDates",
)
async def list_tiss_exam_dates(
    course_number: CourseNumberPath,
    request: Request,
) -> TissExamDateListResponse:
    await current_session_record(request)
    exams = await get_exam_dates(get_app_container(request), course_number)
    return TissExamDateListResponse(
        course_number=course_number,
        exams=[_exam_date_response(exam) for exam in exams],
    )


@router.post(
    "/integrations/tiss/registration/attempts",
    response_model=TissRegistrationAttemptResponse,
    operation_id="createTissRegistrationAttempt",
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorEnvelope},
    },
)
async def create_tiss_registration_attempt(
    payload: TissRegistrationAttemptRequest,
    request: Request,
) -> TissRegistrationAttemptResponse:
    await require_csrf(request)
    effective_semester = payload.semester or current_semester()
    result = await register_course(
        get_app_container(request),
        payload.course_number,
        effective_semester,
        group_id=payload.group_id,
    )
    return TissRegistrationAttemptResponse(
        connection=_connection_state(result.status),
        course_number=payload.course_number,
        semester=effective_semester,
        result=(
            _attempt_result_response(result.registration_result)
            if result.registration_result is not None
            else None
        ),
    )


def _connection_state(service_status: str) -> TissConnectionState:
    state = _CONNECTION_STATES.get(service_status)
    if state is None:
        raise TissError(_UPSTREAM_FAILURE)
    return state


def _favorite_response(favorite: FavoriteCourse) -> TissFavoriteResponse:
    return TissFavoriteResponse(
        course_number=favorite.course_number,
        title=favorite.title,
        course_type=favorite.course_type,
        semester=favorite.semester,
        hours=favorite.hours,
        ects=favorite.ects,
        lva_registered=favorite.lva_registered,
        group_registered=favorite.group_registered,
        exam_registered=favorite.exam_registered,
    )


def _group_response(group: RegistrationGroup) -> TissRegistrationGroupResponse:
    return TissRegistrationGroupResponse(
        group_id=group.group_id,
        name=group.name,
        day=group.day,
        time_start=group.time_start,
        time_end=group.time_end,
        location=group.location,
        capacity=group.capacity,
        enrolled=group.enrolled,
        status=group.status.value,
    )


def _target_response(target: RegistrationTarget) -> TissRegistrationTargetResponse:
    return TissRegistrationTargetResponse(
        course_number=target.course_number,
        semester=target.semester,
        registration_type=target.registration_type.value,
        title=target.title,
        registration_start=target.registration_start,
        registration_end=target.registration_end,
        status=target.status.value,
        groups=[_group_response(group) for group in target.groups],
    )


def _attempt_result_response(
    result: RegistrationResult,
) -> TissRegistrationAttemptResultResponse:
    return TissRegistrationAttemptResultResponse(
        course_number=result.course_number,
        registration_type=result.registration_type.value,
        success=result.success,
        group_name=result.group_name,
        message=result.message,
        attempted_at=result.attempted_at,
    )


def _exam_date_response(exam: TissExamDate) -> TissExamDateResponse:
    return TissExamDateResponse(
        exam_id=exam.exam_id,
        course_number=exam.course_number,
        title=exam.title,
        date_start=exam.date_start,
        date_end=exam.date_end,
        registration_start=exam.registration_start,
        registration_end=exam.registration_end,
        mode=exam.mode,
    )
