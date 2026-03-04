"""Tests for the discovery pipeline."""

from __future__ import annotations

from typing import Any

import pytest

from sophia.domain.events import ExtractionReport
from sophia.domain.models import (
    BookReference,
    Course,
    CourseSection,
    ModuleInfo,
    ReferenceSource,
)
from sophia.services.pipeline import discover_books

# --- Fake implementations of the Protocol interfaces ---


class FakeCourseProvider:
    """Implements CourseProvider protocol for testing."""

    def __init__(
        self,
        courses: list[Course],
        sections: dict[int, list[CourseSection]] | None = None,
        *,
        failing_courses: set[int] | None = None,
    ) -> None:
        self._courses = courses
        self._sections = sections or {}
        self._failing_courses = failing_courses or set()

    async def get_enrolled_courses(self, classification: str = "inprogress") -> list[Course]:
        return self._courses

    async def get_course_content(self, course_id: int) -> list[CourseSection]:
        if course_id in self._failing_courses:
            msg = f"Simulated failure for course {course_id}"
            raise RuntimeError(msg)
        return self._sections.get(course_id, [])


class FakeResourceProvider:
    """Implements ResourceProvider protocol for testing."""

    def __init__(
        self,
        books: list[ModuleInfo] | None = None,
        pages: list[ModuleInfo] | None = None,
        resources: list[ModuleInfo] | None = None,
        urls: list[ModuleInfo] | None = None,
        *,
        failing: bool = False,
    ) -> None:
        self._books = books or []
        self._pages = pages or []
        self._resources = resources or []
        self._urls = urls or []
        self._failing = failing

    async def get_course_books(self, course_ids: list[int]) -> list[ModuleInfo]:
        if self._failing:
            raise RuntimeError("Service not available")
        return self._books

    async def get_course_pages(self, course_ids: list[int]) -> list[ModuleInfo]:
        if self._failing:
            raise RuntimeError("Service not available")
        return self._pages

    async def get_course_resources(self, course_ids: list[int]) -> list[ModuleInfo]:
        if self._failing:
            raise RuntimeError("Service not available")
        return self._resources

    async def get_course_urls(self, course_ids: list[int]) -> list[ModuleInfo]:
        if self._failing:
            raise RuntimeError("Service not available")
        return self._urls


class FakeExtractor:
    """Implements ReferenceExtractor protocol for testing."""

    def __init__(self, mapping: dict[str, list[BookReference]] | None = None) -> None:
        self._mapping = mapping or {}

    def extract(self, content: str, source: ReferenceSource, course_id: int) -> list[BookReference]:
        return self._mapping.get(content, [])


# --- Fixtures ---

COURSE_A = Course(id=1, fullname="Linear Algebra", shortname="LA")
COURSE_B = Course(id=2, fullname="Operating Systems", shortname="OS")


def _make_section(
    section_id: int, name: str, summary: str, modules: list[ModuleInfo] | None = None
) -> CourseSection:
    return CourseSection(id=section_id, name=name, summary=summary, modules=modules or [])


def _make_ref(
    title: str,
    isbn: str | None = None,
    source: ReferenceSource = ReferenceSource.DESCRIPTION,
    course_id: int = 0,
    authors: list[str] | None = None,
) -> BookReference:
    return BookReference(
        title=title,
        isbn=isbn,
        source=source,
        course_id=course_id,
        authors=authors or [],
    )


# --- Tests ---


async def test_basic_discovery() -> None:
    """Happy path: courses with ISBN-bearing sections produce references."""
    summary_html = "<p>ISBN 978-0-13-468599-1</p>"
    sections = {1: [_make_section(10, "Week 1", summary_html)]}
    ref = _make_ref("", isbn="9780134685991", course_id=1)

    course_provider = FakeCourseProvider([COURSE_A], sections)
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor({summary_html: [ref]})

    result = await discover_books(course_provider, resource_provider, extractor)

    assert len(result) == 1
    assert result[0].isbn == "9780134685991"
    assert result[0].course_name == "Linear Algebra"


async def test_per_course_error_isolation() -> None:
    """One course failing doesn't prevent others from being processed."""
    summary_html = "<p>ISBN 978-3-540-00000-0</p>"
    sections = {2: [_make_section(20, "Intro", summary_html)]}
    ref = _make_ref("", isbn="9783540000000", course_id=2)

    course_provider = FakeCourseProvider(
        [COURSE_A, COURSE_B],
        sections,
        failing_courses={1},
    )
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor({summary_html: [ref]})

    events: list[Any] = []
    result = await discover_books(
        course_provider, resource_provider, extractor, on_event=events.append
    )

    assert len(result) == 1
    assert result[0].isbn == "9783540000000"
    assert result[0].course_name == "Operating Systems"

    # ExtractionReport should reflect the failure
    assert len(events) == 1
    report = events[0]
    assert isinstance(report, ExtractionReport)
    assert report.total_courses == 2
    assert report.successful == 1
    assert len(report.failed) == 1
    assert report.failed[0][0] == "Linear Algebra"


async def test_empty_courses() -> None:
    """No references found returns empty list."""
    course_provider = FakeCourseProvider([COURSE_A])
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor()

    result = await discover_books(course_provider, resource_provider, extractor)

    assert result == []


async def test_no_enrolled_courses() -> None:
    """No enrolled courses returns empty list and correct report."""
    events: list[Any] = []
    course_provider = FakeCourseProvider([])
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor()

    result = await discover_books(
        course_provider, resource_provider, extractor, on_event=events.append
    )

    assert result == []
    assert len(events) == 1
    report = events[0]
    assert isinstance(report, ExtractionReport)
    assert report.total_courses == 0
    assert report.total_references == 0


async def test_event_emission() -> None:
    """ExtractionReport event is emitted with correct counts."""
    summary = "<p>Some reference</p>"
    sections = {
        1: [_make_section(10, "S1", summary)],
        2: [_make_section(20, "S2", summary)],
    }
    ref_a = _make_ref("Book A", course_id=1)
    ref_b = _make_ref("Book B", course_id=2)

    course_provider = FakeCourseProvider([COURSE_A, COURSE_B], sections)
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor({summary: [ref_a, ref_b]})

    events: list[Any] = []
    result = await discover_books(
        course_provider, resource_provider, extractor, on_event=events.append
    )

    assert len(events) == 1
    report = events[0]
    assert isinstance(report, ExtractionReport)
    assert report.total_courses == 2
    assert report.successful == 2
    assert report.failed == []
    assert report.total_references == len(result)


async def test_deduplication_by_isbn() -> None:
    """Same ISBN from multiple courses is deduplicated."""
    summary_a = "<p>ISBN 978-0-13-468599-1 in course A</p>"
    summary_b = "<p>ISBN 978-0-13-468599-1 in course B</p>"
    sections = {
        1: [_make_section(10, "S1", summary_a)],
        2: [_make_section(20, "S2", summary_b)],
    }
    ref_a = _make_ref("Effective Java", isbn="9780134685991", course_id=1)
    ref_b = _make_ref("Effective Java", isbn="9780134685991", course_id=2)

    course_provider = FakeCourseProvider([COURSE_A, COURSE_B], sections)
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor({summary_a: [ref_a], summary_b: [ref_b]})

    result = await discover_books(course_provider, resource_provider, extractor)

    assert len(result) == 1
    assert result[0].isbn == "9780134685991"


async def test_deduplication_by_fuzzy_title() -> None:
    """Similar titles without ISBNs are deduplicated via fuzzy matching."""
    summary_a = "Introduction to Algorithms"
    summary_b = "Introduction to Algorithms, 3rd Edition"
    sections = {
        1: [_make_section(10, "S1", summary_a)],
        2: [_make_section(20, "S2", summary_b)],
    }
    ref_a = _make_ref("Introduction to Algorithms", course_id=1)
    ref_b = _make_ref("Introduction to Algorithms, 3rd Edition", course_id=2)

    course_provider = FakeCourseProvider([COURSE_A, COURSE_B], sections)
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor({summary_a: [ref_a], summary_b: [ref_b]})

    result = await discover_books(course_provider, resource_provider, extractor)

    # Fuzzy ratio between these titles is ~0.84, above 0.8 threshold
    assert len(result) == 1


async def test_module_names_extracted() -> None:
    """Module names from sections are passed to the extractor as RESOURCE_NAME."""
    module = ModuleInfo(id=100, name="Cormen_IntroToAlgorithms.pdf", modname="resource")
    sections = {1: [_make_section(10, "Resources", "", modules=[module])]}
    ref = _make_ref("Intro To Algorithms", course_id=1, authors=["Cormen"])

    course_provider = FakeCourseProvider([COURSE_A], sections)
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor({"Cormen_IntroToAlgorithms.pdf": [ref]})

    result = await discover_books(course_provider, resource_provider, extractor)

    assert len(result) == 1
    assert result[0].title == "Intro To Algorithms"


async def test_module_description_extracted() -> None:
    """Module descriptions (raw HTML) are combined within a section for extraction."""
    desc = "<ul><li>J. Kleinberg: <i>Algorithm Design</i>, Pearson, 2005</li></ul>"
    module = ModuleInfo(id=400, name="Literature", modname="label", description=desc)
    sections = {1: [_make_section(10, "Week 1", "", modules=[module])]}
    ref = _make_ref("Algorithm Design", course_id=1, source=ReferenceSource.DESCRIPTION)

    course_provider = FakeCourseProvider([COURSE_A], sections)
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor({desc: [ref]})

    result = await discover_books(course_provider, resource_provider, extractor)

    assert len(result) == 1
    assert result[0].title == "Algorithm Design"


async def test_books_and_pages_extracted() -> None:
    """Books and pages from ResourceProvider are processed."""
    book_mod = ModuleInfo(id=200, name="Digital Design Textbook", modname="book")
    page_mod = ModuleInfo(id=201, name="Recommended Reading", modname="page")
    ref_book = _make_ref("Digital Design Textbook", course_id=1)
    ref_page = _make_ref("Reading List", course_id=1)

    course_provider = FakeCourseProvider([COURSE_A])
    resource_provider = FakeResourceProvider(books=[book_mod], pages=[page_mod])
    extractor = FakeExtractor(
        {
            "Digital Design Textbook": [ref_book],
            "Recommended Reading": [ref_page],
        }
    )

    result = await discover_books(course_provider, resource_provider, extractor)

    assert len(result) == 2


@pytest.mark.parametrize(
    ("title_a", "title_b", "expected_count"),
    [
        ("Algorithms", "Algorithms", 1),
        ("Algorithms", "Data Structures", 2),
        ("Introduction to Algorithms", "Introduction to Algorithms 4th Ed", 1),
    ],
    ids=["identical", "different", "similar"],
)
async def test_deduplication_parametrized(title_a: str, title_b: str, expected_count: int) -> None:
    """Parametrized deduplication scenarios."""
    sections = {
        1: [_make_section(10, "S1", title_a)],
        2: [_make_section(20, "S2", title_b)],
    }
    ref_a = _make_ref(title_a, course_id=1)
    ref_b = _make_ref(title_b, course_id=2)

    course_provider = FakeCourseProvider([COURSE_A, COURSE_B], sections)
    resource_provider = FakeResourceProvider()
    extractor = FakeExtractor({title_a: [ref_a], title_b: [ref_b]})

    result = await discover_books(course_provider, resource_provider, extractor)

    assert len(result) == expected_count


async def test_resource_fetch_failure_graceful() -> None:
    """Resource API failures don't discard section-extracted references."""
    summary = "<p>ISBN 978-0-13-468599-1</p>"
    sections = {1: [_make_section(10, "Week 1", summary)]}
    ref = _make_ref("Effective Java", isbn="9780134685991", course_id=1)

    course_provider = FakeCourseProvider([COURSE_A], sections)
    resource_provider = FakeResourceProvider(failing=True)
    extractor = FakeExtractor({summary: [ref]})

    events: list[Any] = []
    result = await discover_books(
        course_provider, resource_provider, extractor, on_event=events.append
    )

    # Section refs should still be returned despite resource API failure
    assert len(result) == 1
    assert result[0].isbn == "9780134685991"

    report = events[0]
    assert isinstance(report, ExtractionReport)
    assert report.successful == 1
    assert report.failed == []
