"""API error transport schemas."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel, JsonPrimitive


class ErrorDetail(ApiModel):
    code: str
    params: dict[str, JsonPrimitive] = Field(default_factory=dict)


class ErrorEnvelope(ApiModel):
    detail: ErrorDetail
