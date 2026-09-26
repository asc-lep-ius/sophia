"""Settings API transport schemas."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class SettingsResponse(ApiModel):
    theme: str
    locale: str


class SettingsPatchRequest(ApiModel):
    theme: str | None = Field(default=None, min_length=1)
    locale: str | None = Field(default=None, min_length=1)
