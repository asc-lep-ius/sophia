"""Reserved routers: visible in the contract, unavailable at runtime.

These endpoints exist so the shape of the instructor-facing and tutoring
surfaces is part of the published contract before the features land. Every one
of them answers 501 with ``feature.not_implemented``; none of them touches the
database. They are the honest alternative to shipping a stub that returns
plausible-looking empty data a client cannot distinguish from real emptiness.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException

from sophia.api.schemas.errors import FeatureNotImplementedEnvelope

router = APIRouter()

_RESERVED_RESPONSES: dict[int | str, dict[str, Any]] = {
    HTTPStatus.NOT_IMPLEMENTED: {"model": FeatureNotImplementedEnvelope},
}


@router.post(
    "/tutoring/turns",
    status_code=HTTPStatus.NOT_IMPLEMENTED,
    response_model=FeatureNotImplementedEnvelope,
    operation_id="requestTutoringTurn",
    responses=_RESERVED_RESPONSES,
    tags=["tutoring"],
)
async def request_tutoring_turn() -> NoReturn:
    _reserved()


@router.get(
    "/worked-examples",
    status_code=HTTPStatus.NOT_IMPLEMENTED,
    response_model=FeatureNotImplementedEnvelope,
    operation_id="listWorkedExamples",
    responses=_RESERVED_RESPONSES,
    tags=["worked-examples"],
)
async def list_worked_examples() -> NoReturn:
    _reserved()


@router.get(
    "/problems",
    status_code=HTTPStatus.NOT_IMPLEMENTED,
    response_model=FeatureNotImplementedEnvelope,
    operation_id="listProblems",
    responses=_RESERVED_RESPONSES,
    tags=["problems"],
)
async def list_problems() -> NoReturn:
    _reserved()


@router.get(
    "/instructor/provenance-review",
    status_code=HTTPStatus.NOT_IMPLEMENTED,
    response_model=FeatureNotImplementedEnvelope,
    operation_id="listInstructorProvenanceReview",
    responses=_RESERVED_RESPONSES,
    tags=["instructor"],
)
async def list_instructor_provenance_review() -> NoReturn:
    _reserved()


def _reserved() -> NoReturn:
    raise HTTPException(status_code=HTTPStatus.NOT_IMPLEMENTED)
