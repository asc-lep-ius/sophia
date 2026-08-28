"""Health transport schemas."""

from __future__ import annotations

from typing import Literal

from sophia.api.schemas.common import ApiModel


class HealthResponse(ApiModel):
    status: Literal["ok"]


class ReadinessCheck(ApiModel):
    name: Literal["database", "sse_broker"]
    ok: bool


class ReadinessResponse(ApiModel):
    status: Literal["ready", "not_ready"]
    checks: list[ReadinessCheck]
