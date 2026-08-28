"""Metrics transport schemas."""

from __future__ import annotations

from typing import Literal

from sophia.api.schemas.common import ApiModel


class WebVitalsReservedResponse(ApiModel):
    status: Literal["reserved"]
    code: Literal["metrics.web_vitals.reserved"]
