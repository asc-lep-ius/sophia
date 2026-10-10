"""Processing API request DTOs."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class IngestionSettingsRequest(ApiModel):
    """How a learning path is processed from now on.

    ``transcription_language`` is an ISO 639-1 code, or null to let the
    transcriber detect each recording's language itself.
    """

    subscribed: bool
    transcription_language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
