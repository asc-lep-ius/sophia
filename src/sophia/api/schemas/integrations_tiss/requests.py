"""TISS integration API request DTOs."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class TissRegistrationAttemptRequest(ApiModel):
    course_number: str = Field(pattern=r"^\d{3}\.[A-Za-z0-9]{3}$")
    semester: str | None = Field(default=None, pattern=r"^\d{4}[SW]$")
    group_id: str | None = Field(default=None, min_length=1)
