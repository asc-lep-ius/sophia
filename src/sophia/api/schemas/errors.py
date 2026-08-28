"""API error transport schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from sophia.api.schemas.common import ApiModel, JsonPrimitive


class ErrorDetail(ApiModel):
    code: str
    params: dict[str, JsonPrimitive] = Field(default_factory=dict)


class ErrorEnvelope(ApiModel):
    detail: ErrorDetail


class FeatureNotImplementedDetail(ApiModel):
    """Detail body of a reserved endpoint's 501 response."""

    code: Literal["feature.not_implemented"] = "feature.not_implemented"


class FeatureNotImplementedEnvelope(ApiModel):
    """Envelope returned by every reserved-but-unavailable endpoint.

    Named rather than reusing ``ErrorEnvelope`` so the generated client can see
    at the type level that a reserved route has exactly one outcome.
    """

    detail: FeatureNotImplementedDetail
