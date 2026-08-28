"""API error envelope and domain exception handlers."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from sophia.api.context import get_scope_request_id
from sophia.api.schemas.common import JsonPrimitive  # noqa: TC001 — used in runtime cast
from sophia.api.schemas.errors import ErrorDetail, ErrorEnvelope
from sophia.domain.errors import (
    AthenaError,
    AuthError,
    ChronosError,
    EngagementPolicyUnmet,
    HermesError,
    MoodleError,
    RegistrationError,
    SophiaError,
    TissError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI, Request


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    code: str
    status_code: int


_DEFAULT_ERROR_SPEC = ErrorSpec("sophia.failed", HTTPStatus.INTERNAL_SERVER_ERROR)
_DEFAULT_HTTP_ERROR_CODE = "http.failed"
_HTTP_ERROR_CODES: dict[int, str] = {
    HTTPStatus.NOT_FOUND: "http.not_found",
    HTTPStatus.METHOD_NOT_ALLOWED: "http.method_not_allowed",
    HTTPStatus.NOT_IMPLEMENTED: "feature.not_implemented",
}
_DOMAIN_ERROR_SPECS: tuple[tuple[type[SophiaError], ErrorSpec], ...] = (
    (AuthError, ErrorSpec("auth.failed", HTTPStatus.UNAUTHORIZED)),
    (
        EngagementPolicyUnmet,
        ErrorSpec("engagement.policy_unmet", HTTPStatus.PRECONDITION_FAILED),
    ),
    (MoodleError, ErrorSpec("moodle.failed", HTTPStatus.BAD_GATEWAY)),
    (TissError, ErrorSpec("tiss.failed", HTTPStatus.BAD_GATEWAY)),
    (RegistrationError, ErrorSpec("registration.failed", HTTPStatus.CONFLICT)),
    (HermesError, ErrorSpec("hermes.failed", HTTPStatus.INTERNAL_SERVER_ERROR)),
    (AthenaError, ErrorSpec("athena.failed", HTTPStatus.INTERNAL_SERVER_ERROR)),
    (ChronosError, ErrorSpec("chronos.failed", HTTPStatus.INTERNAL_SERVER_ERROR)),
    (SophiaError, _DEFAULT_ERROR_SPEC),
)


def register_error_handlers(api_app: FastAPI) -> None:
    api_app.add_exception_handler(SophiaError, domain_exception_handler)
    api_app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    api_app.add_exception_handler(RequestValidationError, validation_exception_handler)
    api_app.add_exception_handler(Exception, unhandled_exception_handler)


async def domain_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    spec = _spec_for_exception(exc)
    return _error_response(spec, params=_error_params(exc))


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return _error_response(_DEFAULT_ERROR_SPEC)
    code = _HTTP_ERROR_CODES.get(exc.status_code, _DEFAULT_HTTP_ERROR_CODE)
    return _error_response(ErrorSpec(code=code, status_code=exc.status_code), headers=exc.headers)


async def validation_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    spec = ErrorSpec("request.validation_failed", HTTPStatus.UNPROCESSABLE_ENTITY)
    return _error_response(spec)


async def unhandled_exception_handler(request: Request, _exc: Exception) -> JSONResponse:
    return _error_response(_DEFAULT_ERROR_SPEC, headers=_request_id_headers(request))


def _spec_for_exception(exc: Exception) -> ErrorSpec:
    if not isinstance(exc, SophiaError):
        return _DEFAULT_ERROR_SPEC
    for error_type, spec in _DOMAIN_ERROR_SPECS:
        if isinstance(exc, error_type):
            return spec
    return _DEFAULT_ERROR_SPEC


def _error_params(exc: Exception) -> dict[str, JsonPrimitive]:
    """Read the machine-readable reason a domain error chose to publish."""
    params = cast("object", getattr(exc, "params", None))
    if not isinstance(params, dict):
        return {}
    items = cast("dict[object, object]", params).items()
    return {str(key): cast("JsonPrimitive", value) for key, value in items}


def _error_response(
    spec: ErrorSpec,
    headers: Mapping[str, str] | None = None,
    *,
    params: dict[str, JsonPrimitive] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(detail=ErrorDetail(code=spec.code, params=params or {}))
    return JSONResponse(
        status_code=spec.status_code,
        content=envelope.model_dump(),
        headers=headers,
    )


def _request_id_headers(request: Request) -> dict[str, str]:
    request_id = get_scope_request_id(request.scope)
    if request_id is None:
        return {}
    return {"X-Request-ID": request_id}
