"""Async Moodle adapter — implements CourseProvider, ResourceProvider, AssignmentProvider."""

from __future__ import annotations

import base64
from typing import Any

import httpx
import structlog

from sophia.domain.errors import AuthError, MoodleError
from sophia.domain.models import (
    AssignmentInfo,
    CheckmarkInfo,
    ContentInfo,
    Course,
    CourseSection,
    GradeItem,
    ModuleInfo,
    QuizInfo,
)

log = structlog.get_logger()

# Moodle error keys that indicate an expired or invalid token
_AUTH_ERROR_CODES = frozenset(
    {
        "invalidtoken",
        "accessexception",
        "invalidlogin",
        "sitenotfound",
        "forcepasswordchangenotice",
        "usernotfullysetup",
    }
)

_TOKEN_VALIDATION_FUNCTION = "core_webservice_get_site_info"


def parse_token(raw: str) -> str:
    """Extract a Moodle WS token from a raw string or moodlemobile:// URL."""
    if not raw.startswith("moodlemobile"):
        return raw
    try:
        _, b64part = raw.split("=", 1)
        decoded = base64.b64decode(b64part.encode("ascii")).decode("ascii")
        return decoded.split(":::")[1]
    except (ValueError, IndexError) as exc:
        raise AuthError(f"Malformed moodlemobile:// URL: {raw}") from exc


def _encode_course_ids(course_ids: list[int]) -> dict[str, str | int]:
    """Moodle expects indexed form params: courseids[0]=1&courseids[1]=2."""
    return {f"courseids[{i}]": cid for i, cid in enumerate(course_ids)}


class MoodleAdapter:
    """Async Moodle web-service adapter.

    Satisfies: CourseProvider, ResourceProvider, AssignmentProvider protocols.
    """

    def __init__(self, http: httpx.AsyncClient, token: str, host: str) -> None:
        self._http = http
        self._token = parse_token(token)
        self._endpoint = f"{host.rstrip('/')}/webservice/rest/server.php"

    # ------------------------------------------------------------------
    # Low-level transport
    # ------------------------------------------------------------------

    async def _call(self, function: str, params: dict[str, Any] | None = None) -> Any:
        """POST to the Moodle REST API and return parsed JSON.

        Raises MoodleError for Moodle-level errors and AuthError for token issues.
        """
        form: dict[str, Any] = {
            "wstoken": self._token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
        }
        if params:
            form.update(params)

        response = await self._http.post(self._endpoint, data=form)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MoodleError(f"HTTP {exc.response.status_code} from Moodle API") from exc
        body = response.json()

        if isinstance(body, dict) and "exception" in body:
            errorcode = body.get("errorcode", "")
            message = body.get("message", str(body))
            if errorcode in _AUTH_ERROR_CODES:
                raise AuthError(message)
            raise MoodleError(f"[{errorcode}] {message}")

        return body

    # ------------------------------------------------------------------
    # Token validation
    # ------------------------------------------------------------------

    async def check_token(self) -> None:
        """Fail-fast token validation — call before expensive operations."""
        await self._call(_TOKEN_VALIDATION_FUNCTION)

    # ------------------------------------------------------------------
    # CourseProvider
    # ------------------------------------------------------------------

    async def get_enrolled_courses(self, classification: str = "inprogress") -> list[Course]:
        data = await self._call(
            "core_course_get_enrolled_courses_by_timeline_classification",
            {"classification": classification, "limit": 0},
        )
        return [
            Course(
                id=c["id"],
                fullname=c["fullname"],
                shortname=c["shortname"],
                url=c.get("viewurl"),
            )
            for c in data["courses"]
        ]

    async def get_course_content(self, course_id: int) -> list[CourseSection]:
        sections = await self._call("core_course_get_contents", {"courseid": course_id})
        return [_parse_section(s) for s in sections]

    # ------------------------------------------------------------------
    # ResourceProvider
    # ------------------------------------------------------------------

    async def get_course_books(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call("mod_book_get_books_by_courses", _encode_course_ids(course_ids))
        return [_parse_module(b, modname="book") for b in data["books"]]

    async def get_course_pages(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call("mod_page_get_pages_by_courses", _encode_course_ids(course_ids))
        return [_parse_module(p, modname="page") for p in data["pages"]]

    async def get_course_resources(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call(
            "mod_resource_get_resources_by_courses", _encode_course_ids(course_ids)
        )
        return [_parse_module(r, modname="resource") for r in data["resources"]]

    async def get_course_urls(self, course_ids: list[int]) -> list[ModuleInfo]:
        data = await self._call("mod_url_get_urls_by_courses", _encode_course_ids(course_ids))
        return [_parse_module(u, modname="url") for u in data["urls"]]

    # ------------------------------------------------------------------
    # AssignmentProvider
    # ------------------------------------------------------------------

    async def get_assignments(self, course_ids: list[int]) -> list[AssignmentInfo]:
        data = await self._call("mod_assign_get_assignments", _encode_course_ids(course_ids))
        return [
            AssignmentInfo(
                id=a["id"],
                name=a["name"],
                course_id=c["id"],
                due_date=str(a["duedate"]) if a.get("duedate") else None,
            )
            for c in data["courses"]
            for a in c["assignments"]
        ]

    async def get_quizzes(self, course_ids: list[int]) -> list[QuizInfo]:
        data = await self._call("mod_quiz_get_quizzes_by_courses", _encode_course_ids(course_ids))
        return [
            QuizInfo(id=q["id"], name=q["name"], course_id=q["course"]) for q in data["quizzes"]
        ]

    async def get_checkmarks(self, course_ids: list[int]) -> list[CheckmarkInfo]:
        data = await self._call(
            "mod_checkmark_get_checkmarks_by_courses", _encode_course_ids(course_ids)
        )
        return [
            CheckmarkInfo(
                id=cm["id"],
                name=cm["name"],
                course_id=cm["course"],
                completed=bool(cm.get("completed", False)),
            )
            for cm in data["checkmarks"]
        ]

    async def get_grade_items(self, course_id: int) -> list[GradeItem]:
        data = await self._call("gradereport_user_get_grade_items", {"courseid": course_id})
        user_grades = data.get("usergrades", [])
        if not user_grades:
            return []
        return [
            GradeItem(
                id=gi["id"],
                name=gi.get("itemname", ""),
                grade=gi.get("graderaw"),
                max_grade=gi.get("grademax"),
            )
            for gi in user_grades[0]["gradeitems"]
        ]


# ------------------------------------------------------------------
# Response-parsing helpers
# ------------------------------------------------------------------


def _parse_section(raw: dict[str, Any]) -> CourseSection:
    return CourseSection(
        id=raw["id"],
        name=raw["name"],
        summary=raw.get("summary", ""),
        modules=[_parse_section_module(m) for m in raw.get("modules", [])],
    )


def _parse_section_module(raw: dict[str, Any]) -> ModuleInfo:
    return ModuleInfo(
        id=raw["id"],
        name=raw["name"],
        modname=raw.get("modname", ""),
        url=raw.get("url"),
        contents=[
            ContentInfo(
                filename=c["filename"],
                fileurl=c["fileurl"],
                filesize=c.get("filesize", 0),
                mimetype=c.get("mimetype", ""),
            )
            for c in raw.get("contents", [])
        ],
    )


def _parse_module(raw: dict[str, Any], *, modname: str) -> ModuleInfo:
    """Parse a flat resource/book/page/url response into ModuleInfo."""
    return ModuleInfo(
        id=raw["id"],
        name=raw["name"],
        modname=modname,
        url=raw.get("url"),
    )
