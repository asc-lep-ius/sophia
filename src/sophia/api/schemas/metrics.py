"""Metrics transport schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class WebVitalsMetricName(StrEnum):
    """The field metrics the study surface reports.

    A closed set, because each value becomes a Prometheus label: an open string
    would let a client mint unbounded series.
    """

    CLS = "CLS"
    FCP = "FCP"
    INP = "INP"
    LCP = "LCP"
    TTFB = "TTFB"


class WebVitalsRating(StrEnum):
    """The library's own verdict on a measurement, kept as its bucket."""

    GOOD = "good"
    NEEDS_IMPROVEMENT = "needs_improvement"
    POOR = "poor"


class WebVitalsReportRequest(ApiModel):
    """One field measurement from a real session.

    Deliberately carries no identifiers: this is aggregate responsiveness
    evidence, and a per-learner interaction trace is a different thing with
    different consent requirements.
    """

    metric_name: WebVitalsMetricName
    rating: WebVitalsRating
    value: float = Field(ge=0.0)
    navigation_type: str | None = Field(default=None, max_length=32)


class WebVitalsAcceptedResponse(ApiModel):
    status: Literal["accepted"]
    code: Literal["metrics.web_vitals.accepted"]
