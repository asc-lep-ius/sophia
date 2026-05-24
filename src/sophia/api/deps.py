"""FastAPI dependency stubs for current request scope."""

from __future__ import annotations

from sophia.api.context import get_request_context
from sophia.api.schemas.common import CohortScope, CourseScope, OrgScope, RoleScope, UserScope


async def current_org() -> OrgScope:
    context = get_request_context()
    return OrgScope(id=context.org_id if context else "local", display_name="Local")


async def current_course() -> CourseScope:
    context = get_request_context()
    return CourseScope(
        id=context.course_id if context else "default-course",
        display_name="Default Course",
    )


async def current_cohort() -> CohortScope:
    context = get_request_context()
    return CohortScope(
        id=context.cohort_id if context else "default-cohort",
        display_name="Default Cohort",
    )


async def current_user() -> UserScope:
    context = get_request_context()
    return UserScope(
        id=context.user_id if context else "anonymous",
        display_name="Anonymous",
    )


async def current_role() -> RoleScope:
    context = get_request_context()
    return RoleScope(value=context.role if context else "student")
