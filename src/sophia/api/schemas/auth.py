"""Auth and session API transport schemas."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel
from sophia.api.schemas.settings import SettingsResponse  # noqa: TC001


class AuthLoginRequest(ApiModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    mfa_code: str | None = Field(default=None, min_length=1)


class SessionUserResponse(ApiModel):
    id: str
    display_name: str
    email: str


class SessionTenantResponse(ApiModel):
    org_id: str
    # Null until a learning path is selected; required so a client has to
    # handle that state rather than read a missing key as a default.
    learning_path_id: str | None
    cohort_id: str | None = None
    role: str


class AuthSessionResponse(ApiModel):
    authenticated: bool
    user: SessionUserResponse | None = None
    tenant: SessionTenantResponse | None = None
    settings: SettingsResponse | None = None
    csrf_token: str | None = None
