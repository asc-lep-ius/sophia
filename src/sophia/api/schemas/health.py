"""Health transport schemas."""

from __future__ import annotations

from typing import Literal

from sophia.api.schemas.common import ApiModel


class HealthResponse(ApiModel):
    status: Literal["ok"]


class ReadinessCheck(ApiModel):
    name: Literal["database", "sse_broker", "upstream_session"]
    ok: bool
    # A check that is not required reports a degraded dependency without
    # making the service unready: pages that need no TU Wien session still work.
    required: bool = True
    detail: str | None = None


class ReadinessResponse(ApiModel):
    status: Literal["ready", "not_ready"]
    checks: list[ReadinessCheck]
