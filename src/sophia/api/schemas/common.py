"""Common API transport schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

type JsonPrimitive = str | int | float | bool | None


class ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class OrgScope(ApiModel):
    id: str
    display_name: str


class LearningPathScope(ApiModel):
    id: str
    display_name: str


class CohortScope(ApiModel):
    id: str
    display_name: str


class UserScope(ApiModel):
    id: str
    display_name: str


class RoleScope(ApiModel):
    value: str
