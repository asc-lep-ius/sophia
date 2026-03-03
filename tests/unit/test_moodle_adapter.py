"""Tests for the async Moodle adapter."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from sophia.adapters.moodle import MoodleAdapter, parse_token
from sophia.domain.errors import AuthError, MoodleError
from sophia.domain.models import (
    AssignmentInfo,
    CheckmarkInfo,
    Course,
    CourseSection,
    GradeItem,
    ModuleInfo,
    QuizInfo,
)
from sophia.domain.ports import AssignmentProvider, CourseProvider, ResourceProvider


# Structural conformance helper: verify the adapter has every method the protocol declares
def _conforms_to(instance: object, protocol: type) -> bool:
    """Check structural conformance without requiring @runtime_checkable."""
    hints = {
        name
        for name in dir(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }
    return all(callable(getattr(instance, name, None)) for name in hints)


HOST = "https://tuwel.tuwien.ac.at"
ENDPOINT = f"{HOST}/webservice/rest/server.php"
TOKEN = "abc123validtoken"


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


@pytest.fixture
def adapter(client: httpx.AsyncClient) -> MoodleAdapter:
    return MoodleAdapter(http=client, token=TOKEN, host=HOST)


# ------------------------------------------------------------------
# Token parsing
# ------------------------------------------------------------------


class TestParseToken:
    def test_plain_token_passthrough(self):
        assert parse_token("abc123") == "abc123"

    def test_moodlemobile_url(self):
        payload = base64.b64encode(b"https://tuwel.tuwien.ac.at:::secrettoken").decode("ascii")
        url = f"moodlemobile://token={payload}"
        assert parse_token(url) == "secrettoken"

    def test_adapter_parses_moodlemobile_on_init(self, client: httpx.AsyncClient):
        payload = base64.b64encode(b"host:::mytoken").decode("ascii")
        url = f"moodlemobile://token={payload}"
        adapter = MoodleAdapter(http=client, token=url, host=HOST)
        assert adapter._token == "mytoken"  # noqa: SLF001

    def test_malformed_moodlemobile_url_raises_auth_error(self):
        with pytest.raises(AuthError, match="Malformed"):
            parse_token("moodlemobile://garbage")


# ------------------------------------------------------------------
# check_token
# ------------------------------------------------------------------


class TestCheckToken:
    @respx.mock
    async def test_valid_token(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"sitename": "TUWEL"}))
        await adapter.check_token()

    @respx.mock
    async def test_expired_token_raises_auth_error(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "exception": "moodle_exception",
                    "errorcode": "invalidtoken",
                    "message": "Invalid token",
                },
            )
        )
        with pytest.raises(AuthError, match="Invalid token"):
            await adapter.check_token()


# ------------------------------------------------------------------
# CourseProvider
# ------------------------------------------------------------------


class TestGetEnrolledCourses:
    @respx.mock
    async def test_returns_courses(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "courses": [
                        {
                            "id": 1,
                            "fullname": "Linear Algebra",
                            "shortname": "LA",
                            "viewurl": "https://tuwel.tuwien.ac.at/course/view.php?id=1",
                        },
                        {
                            "id": 2,
                            "fullname": "Analysis",
                            "shortname": "AN",
                        },
                    ],
                    "nextoffset": 0,
                },
            )
        )
        courses = await adapter.get_enrolled_courses()
        assert len(courses) == 2
        assert all(isinstance(c, Course) for c in courses)
        assert courses[0].id == 1
        assert courses[0].fullname == "Linear Algebra"
        assert courses[0].url == "https://tuwel.tuwien.ac.at/course/view.php?id=1"
        assert courses[1].url is None

    @respx.mock
    async def test_empty_courses(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(200, json={"courses": [], "nextoffset": 0})
        )
        courses = await adapter.get_enrolled_courses()
        assert courses == []


class TestGetCourseContent:
    @respx.mock
    async def test_returns_sections(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 10,
                        "name": "General",
                        "summary": "Welcome",
                        "modules": [
                            {
                                "id": 100,
                                "name": "Syllabus",
                                "modname": "resource",
                                "url": "https://tuwel.tuwien.ac.at/mod/resource/view.php?id=100",
                                "contents": [
                                    {
                                        "filename": "syllabus.pdf",
                                        "fileurl": "https://tuwel.tuwien.ac.at/file.php/1",
                                        "filesize": 12345,
                                        "mimetype": "application/pdf",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            )
        )
        sections = await adapter.get_course_content(course_id=1)
        assert len(sections) == 1
        assert isinstance(sections[0], CourseSection)
        assert sections[0].name == "General"
        assert len(sections[0].modules) == 1
        assert sections[0].modules[0].contents[0].filename == "syllabus.pdf"


# ------------------------------------------------------------------
# ResourceProvider
# ------------------------------------------------------------------


class TestResourceProvider:
    @respx.mock
    async def test_get_course_books(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={"books": [{"id": 1, "name": "Course Book", "url": None}]},
            )
        )
        books = await adapter.get_course_books([1])
        assert len(books) == 1
        assert isinstance(books[0], ModuleInfo)
        assert books[0].modname == "book"

    @respx.mock
    async def test_get_course_pages(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={"pages": [{"id": 2, "name": "Info Page", "url": None}]},
            )
        )
        pages = await adapter.get_course_pages([1])
        assert len(pages) == 1
        assert pages[0].modname == "page"

    @respx.mock
    async def test_get_course_resources(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={"resources": [{"id": 3, "name": "Slides.pdf", "url": None}]},
            )
        )
        resources = await adapter.get_course_resources([1])
        assert len(resources) == 1
        assert resources[0].modname == "resource"

    @respx.mock
    async def test_get_course_urls(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={"urls": [{"id": 4, "name": "External Link", "url": "https://example.com"}]},
            )
        )
        urls = await adapter.get_course_urls([1])
        assert len(urls) == 1
        assert urls[0].modname == "url"
        assert urls[0].url == "https://example.com"


# ------------------------------------------------------------------
# AssignmentProvider
# ------------------------------------------------------------------


class TestGetAssignments:
    @respx.mock
    async def test_flattens_nested_response(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "courses": [
                        {
                            "id": 1,
                            "assignments": [
                                {"id": 10, "name": "HW1", "duedate": 1700000000},
                                {"id": 11, "name": "HW2", "duedate": 0},
                            ],
                        },
                        {
                            "id": 2,
                            "assignments": [
                                {"id": 20, "name": "Project", "duedate": 1700100000},
                            ],
                        },
                    ]
                },
            )
        )
        assignments = await adapter.get_assignments([1, 2])
        assert len(assignments) == 3
        assert all(isinstance(a, AssignmentInfo) for a in assignments)
        assert assignments[0].course_id == 1
        assert assignments[2].course_id == 2
        assert assignments[0].due_date == "1700000000"
        # duedate=0 → None
        assert assignments[1].due_date is None


class TestGetQuizzes:
    @respx.mock
    async def test_returns_quizzes(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "quizzes": [
                        {"id": 5, "name": "Midterm", "course": 1},
                        {"id": 6, "name": "Final", "course": 1},
                    ]
                },
            )
        )
        quizzes = await adapter.get_quizzes([1])
        assert len(quizzes) == 2
        assert all(isinstance(q, QuizInfo) for q in quizzes)
        assert quizzes[0].course_id == 1


class TestGetCheckmarks:
    @respx.mock
    async def test_returns_checkmarks(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "checkmarks": [
                        {"id": 7, "name": "Task 1", "course": 1, "completed": 1},
                        {"id": 8, "name": "Task 2", "course": 1, "completed": 0},
                    ]
                },
            )
        )
        checkmarks = await adapter.get_checkmarks([1])
        assert len(checkmarks) == 2
        assert all(isinstance(cm, CheckmarkInfo) for cm in checkmarks)
        assert checkmarks[0].completed is True
        assert checkmarks[1].completed is False


class TestGetGradeItems:
    @respx.mock
    async def test_returns_grade_items(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "usergrades": [
                        {
                            "gradeitems": [
                                {
                                    "id": 100,
                                    "itemname": "HW1",
                                    "graderaw": 85.0,
                                    "grademax": 100.0,
                                },
                                {
                                    "id": 101,
                                    "itemname": "HW2",
                                    "graderaw": None,
                                    "grademax": 50.0,
                                },
                            ]
                        }
                    ]
                },
            )
        )
        items = await adapter.get_grade_items(course_id=1)
        assert len(items) == 2
        assert all(isinstance(gi, GradeItem) for gi in items)
        assert items[0].grade == 85.0
        assert items[0].max_grade == 100.0
        assert items[1].grade is None

    @respx.mock
    async def test_empty_usergrades_returns_empty_list(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"usergrades": []}))
        items = await adapter.get_grade_items(course_id=99)
        assert items == []


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------


class TestErrorHandling:
    @respx.mock
    async def test_moodle_exception_raises_moodle_error(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "exception": "moodle_exception",
                    "errorcode": "invalidrecord",
                    "message": "Can not find data record",
                },
            )
        )
        with pytest.raises(MoodleError, match="invalidrecord"):
            await adapter.get_enrolled_courses()

    @respx.mock
    async def test_invalid_token_raises_auth_error(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "exception": "moodle_exception",
                    "errorcode": "invalidtoken",
                    "message": "Invalid token - token not found",
                },
            )
        )
        with pytest.raises(AuthError):
            await adapter.get_enrolled_courses()

    @respx.mock
    async def test_access_exception_raises_auth_error(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(
                200,
                json={
                    "exception": "webservice_access_exception",
                    "errorcode": "accessexception",
                    "message": "Access control exception",
                },
            )
        )
        with pytest.raises(AuthError):
            await adapter.get_course_content(1)

    @respx.mock
    async def test_http_error_raises_moodle_error(self, adapter: MoodleAdapter):
        respx.post(ENDPOINT).mock(return_value=httpx.Response(502))
        with pytest.raises(MoodleError, match="502"):
            await adapter.get_enrolled_courses()


# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_course_provider(self, adapter: MoodleAdapter):
        assert _conforms_to(adapter, CourseProvider)

    def test_satisfies_resource_provider(self, adapter: MoodleAdapter):
        assert _conforms_to(adapter, ResourceProvider)

    def test_satisfies_assignment_provider(self, adapter: MoodleAdapter):
        assert _conforms_to(adapter, AssignmentProvider)
