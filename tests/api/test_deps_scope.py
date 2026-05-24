"""Current-scope dependency stub tests."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.testclient import TestClient

from sophia.api import create_api_app
from sophia.api.deps import current_cohort, current_course, current_org, current_role, current_user
from sophia.api.schemas.common import CohortScope, CourseScope, OrgScope, RoleScope, UserScope


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
