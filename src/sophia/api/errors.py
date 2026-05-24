"""API error envelope and domain exception handlers."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from sophia.api.schemas.errors import ErrorDetail, ErrorEnvelope
from sophia.domain.errors import (
    AthenaError,
    AuthError,
    ChronosError,
    HermesError,
    MoodleError,
    RegistrationError,
    SophiaError,
    TissError,
)

if TYPE_CHECKING:
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
}
_DOMAIN_ERROR_SPECS: tuple[tuple[type[SophiaError], ErrorSpec], ...] = (
    (AuthError, ErrorSpec("auth.failed", HTTPStatus.UNAUTHORIZED)),
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


async def domain_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    spec = _spec_for_exception(exc)
    return _error_response(spec)


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return _error_response(_DEFAULT_ERROR_SPEC)
    code = _HTTP_ERROR_CODES.get(exc.status_code, _DEFAULT_HTTP_ERROR_CODE)
    return _error_response(ErrorSpec(code=code, status_code=exc.status_code))


async def validation_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    spec = ErrorSpec("request.validation_failed", HTTPStatus.UNPROCESSABLE_ENTITY)
    return _error_response(spec)


def _spec_for_exception(exc: Exception) -> ErrorSpec:
    if not isinstance(exc, SophiaError):
        return _DEFAULT_ERROR_SPEC
    for error_type, spec in _DOMAIN_ERROR_SPECS:
        if isinstance(exc, error_type):
            return spec
    return _DEFAULT_ERROR_SPEC


def _error_response(spec: ErrorSpec) -> JSONResponse:
    envelope = ErrorEnvelope(detail=ErrorDetail(code=spec.code))
    return JSONResponse(status_code=spec.status_code, content=envelope.model_dump())
