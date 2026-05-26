"""Current-scope dependency tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from sophia.api import create_api_app
from sophia.api.deps import (
    current_cohort,
    current_course,
    current_org,
    current_role,
    current_user,
    get_app_container,
)
from sophia.api.schemas.common import CohortScope, CourseScope, OrgScope, RoleScope, UserScope

from ._session_helpers import build_harness, login

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer


def test_scope_dependencies_return_default_stubs() -> None:
    api_app = create_api_app()

    @api_app.get("/api/_scope")
    async def read_scope(
        org: Annotated[OrgScope, Depends(current_org)],
        course: Annotated[CourseScope, Depends(current_course)],
        cohort: Annotated[CohortScope, Depends(current_cohort)],
        user: Annotated[UserScope, Depends(current_user)],
        role: Annotated[RoleScope, Depends(current_role)],
    ) -> dict[str, str]:
        return {
            "org_id": org.id,
            "course_id": course.id,
            "cohort_id": cohort.id,
            "user_id": user.id,
            "role": role.value,
        }

    response = TestClient(api_app).get("/api/_scope")

    assert response.status_code == 200
    assert response.json() == {
        "org_id": "local",
        "course_id": "default-course",
        "cohort_id": "default-cohort",
        "user_id": "anonymous",
        "role": "student",
    }


def test_scope_dependencies_read_authenticated_session_record() -> None:
    harness = build_harness()

    @harness.app.get("/api/_scope")
    async def read_scope(
        org: Annotated[OrgScope, Depends(current_org)],
        course: Annotated[CourseScope, Depends(current_course)],
        cohort: Annotated[CohortScope, Depends(current_cohort)],
        user: Annotated[UserScope, Depends(current_user)],
        role: Annotated[RoleScope, Depends(current_role)],
    ) -> dict[str, str]:
        return {
            "org_id": org.id,
            "course_id": course.id,
            "cohort_id": cohort.id,
            "user_id": user.id,
            "role": role.value,
        }

    login(harness)
    response = harness.client.get("/api/_scope")

    assert response.status_code == 200
    assert response.json() == {
        "org_id": "tu-wien",
        "course_id": "course-1",
        "cohort_id": "cohort-a",
        "user_id": "learner",
        "role": "student",
    }


def test_scope_dependencies_can_be_overridden() -> None:
    api_app = create_api_app()

    @api_app.get("/api/_user")
    async def read_user(user: Annotated[UserScope, Depends(current_user)]) -> dict[str, str]:
        return {"user_id": user.id, "display_name": user.display_name}

    async def override_user() -> UserScope:
        return UserScope(id="user-123", display_name="Phase Tester")

    api_app.dependency_overrides[current_user] = override_user

    response = TestClient(api_app).get("/api/_user")

    assert response.status_code == 200
    assert response.json() == {"user_id": "user-123", "display_name": "Phase Tester"}


def test_app_container_dependency_reads_injected_harness_container() -> None:
    fake_container = cast("AppContainer", object())
    harness = build_harness(app_container=fake_container)

    @harness.app.get("/api/_container")
    async def read_container(
        app_container: Annotated[object, Depends(get_app_container)],
    ) -> dict[str, bool]:
        return {"same_container": app_container is fake_container}

    response = harness.client.get("/api/_container")

    assert response.status_code == 200
    assert response.json() == {"same_container": True}


def test_app_container_dependency_fails_explicitly_when_missing() -> None:
    api_app = create_api_app()

    @api_app.get("/api/_container")
    async def read_container(
        app_container: Annotated[object, Depends(get_app_container)],
    ) -> dict[str, bool]:
        return {"configured": app_container is not None}

    with pytest.raises(RuntimeError, match="app container is not configured"):
        TestClient(api_app).get("/api/_container")


def test_app_container_dependency_can_be_overridden() -> None:
    api_app = create_api_app()
    fake_container = cast("AppContainer", object())

    @api_app.get("/api/_container")
    async def read_container(
        app_container: Annotated[object, Depends(get_app_container)],
    ) -> dict[str, bool]:
        return {"same_container": app_container is fake_container}

    def override_container() -> object:
        return fake_container

    api_app.dependency_overrides[get_app_container] = override_container

    response = TestClient(api_app).get("/api/_container")

    assert response.status_code == 200
    assert response.json() == {"same_container": True}
