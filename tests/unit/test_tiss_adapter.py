"""Tests for the async TISS adapter (public XML API client)."""

from __future__ import annotations

import httpx
import pytest
import respx

from sophia.adapters.tiss import (
    TissAdapter,
    clean_course_number,
    extract_course_info,
    parse_course_xml,
    parse_exam_dates_xml,
)
from sophia.domain.errors import TissError
from sophia.domain.models import TissCourseInfo, TissExamDate
from sophia.domain.ports import CourseMetadataProvider

HOST = "https://tiss.tuwien.ac.at"
API_COURSE_PATH = "/api/course/"

COURSE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<tpiCourse xmlns="https://tiss.tuwien.ac.at/api/schemas/course/v10"
           xmlns:ns2="https://tiss.tuwien.ac.at/api/schemas/i18n/v10">
  <courseNumber>186866</courseNumber>
  <semester>
    <ns2:de>2026S</ns2:de><ns2:en>2026S</ns2:en>
  </semester>
  <courseType>VU</courseType>
  <title>
    <ns2:de>Algorithmen und Datenstrukturen</ns2:de>
    <ns2:en>Algorithms and Data Structures</ns2:en>
  </title>
  <ects>6.0</ects>
  <teachingContent>
    <ns2:de>Sortieren, Suchen, Graphen</ns2:de>
    <ns2:en>Sorting, searching, graphs</ns2:en>
  </teachingContent>
  <courseObjective>
    <ns2:de>Grundlagen verstehen</ns2:de>
    <ns2:en>Understand fundamentals</ns2:en>
  </courseObjective>
</tpiCourse>
"""

EXAM_DATES_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<examDatesList xmlns="https://tiss.tuwien.ac.at/api/schemas/course/v10">
  <examDate>
    <id>1001</id>
    <title>1. Prüfungstermin</title>
    <startDate>2026-06-15T14:00:00</startDate>
    <endDate>2026-06-15T16:00:00</endDate>
    <registrationFrom>2026-06-01T00:00:00</registrationFrom>
    <registrationTo>2026-06-14T23:59:59</registrationTo>
    <mode>WRITTEN</mode>
  </examDate>
  <examDate>
    <id>1002</id>
    <title>2. Prüfungstermin</title>
    <startDate>2026-09-20T10:00:00</startDate>
    <endDate>2026-09-20T12:00:00</endDate>
    <registrationFrom>2026-09-01T00:00:00</registrationFrom>
    <registrationTo>2026-09-19T23:59:59</registrationTo>
    <mode>WRITTEN</mode>
  </examDate>
</examDatesList>
"""

EMPTY_EXAM_DATES_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<examDatesList xmlns="https://tiss.tuwien.ac.at/api/schemas/course/v10"/>
"""


# Structural conformance helper (from existing test patterns)
def _conforms_to(instance: object, protocol: type) -> bool:
    """Check structural conformance without requiring @runtime_checkable."""
    hints = {
        name
        for name in dir(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }
    return all(callable(getattr(instance, name, None)) for name in hints)


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=HOST)


@pytest.fixture
def adapter(client: httpx.AsyncClient) -> TissAdapter:
    return TissAdapter(http=client, host=HOST)


# ------------------------------------------------------------------
# extract_course_info
# ------------------------------------------------------------------


class TestExtractCourseInfo:
    @pytest.mark.parametrize(
        ("shortname", "expected"),
        [
            ("186.866 Algorithmen und Datenstrukturen 2026S", ("186.866", "2026S")),
            ("185.291 Betriebssysteme UE 2025W", ("185.291", "2025W")),
            ("104.271 Analysis 2026S (Gruppe 1)", ("104.271", "2026S")),
            ("188.952 VU Funktionale Programmierung 2026S", ("188.952", "2026S")),
        ],
    )
    def test_valid_shortnames(self, shortname: str, expected: tuple[str, str]) -> None:
        assert extract_course_info(shortname) == expected

    @pytest.mark.parametrize(
        "shortname",
        [
            "Some Random Course",
            "no-numbers-here",
            "",
            "186.866",  # no semester
            "2026S",  # no course number
        ],
    )
    def test_invalid_shortnames(self, shortname: str) -> None:
        assert extract_course_info(shortname) is None


# ------------------------------------------------------------------
# _clean_course_number
# ------------------------------------------------------------------


class TestCleanCourseNumber:
    def test_removes_dots(self) -> None:
        assert clean_course_number("186.866") == "186866"

    def test_no_dots(self) -> None:
        assert clean_course_number("186866") == "186866"

    def test_multiple_dots(self) -> None:
        assert clean_course_number("1.8.6.8.6.6") == "186866"


# ------------------------------------------------------------------
# _parse_course_xml
# ------------------------------------------------------------------


class TestParseCourseXml:
    def test_parses_full_response(self) -> None:
        result = parse_course_xml(COURSE_XML)

        assert result.course_number == "186.866"
        assert result.semester == "2026S"
        assert result.course_type == "VU"
        assert result.title_de == "Algorithmen und Datenstrukturen"
        assert result.title_en == "Algorithms and Data Structures"
        assert result.ects == 6.0
        assert result.description_de == "Sortieren, Suchen, Graphen"
        assert result.description_en == "Sorting, searching, graphs"
        assert result.objectives_de == "Grundlagen verstehen"
        assert result.objectives_en == "Understand fundamentals"

    def test_minimal_xml(self) -> None:
        xml = (
            '<tpiCourse xmlns="https://tiss.tuwien.ac.at/api/schemas/course/v10"'
            ' xmlns:ns2="https://tiss.tuwien.ac.at/api/schemas/i18n/v10">'
            "<courseNumber>100001</courseNumber>"
            "<semester><ns2:de>2026S</ns2:de></semester></tpiCourse>"
        )
        result = parse_course_xml(xml)

        assert result.course_number == "100.001"
        assert result.semester == "2026S"
        assert result.course_type == ""
        assert result.ects == 0.0


# ------------------------------------------------------------------
# _parse_exam_dates_xml
# ------------------------------------------------------------------


class TestParseExamDatesXml:
    def test_parses_multiple_exams(self) -> None:
        results = parse_exam_dates_xml(EXAM_DATES_XML, "186.866")

        assert len(results) == 2

        first = results[0]
        assert first.exam_id == "1001"
        assert first.course_number == "186.866"
        assert first.title == "1. Prüfungstermin"
        assert first.date_start == "2026-06-15T14:00:00"
        assert first.date_end == "2026-06-15T16:00:00"
        assert first.registration_start == "2026-06-01T00:00:00"
        assert first.registration_end == "2026-06-14T23:59:59"
        assert first.mode == "WRITTEN"

        second = results[1]
        assert second.exam_id == "1002"
        assert second.title == "2. Prüfungstermin"

    def test_empty_exam_list(self) -> None:
        results = parse_exam_dates_xml(EMPTY_EXAM_DATES_XML, "186.866")
        assert results == []


# ------------------------------------------------------------------
# TissAdapter.get_course_details
# ------------------------------------------------------------------


class TestGetCourseDetails:
    @respx.mock
    async def test_fetches_and_parses_course(self, adapter: TissAdapter) -> None:
        respx.get(f"{HOST}/api/course/186866-2026S").mock(
            return_value=httpx.Response(200, text=COURSE_XML)
        )

        result = await adapter.get_course_details("186.866", "2026S")

        assert isinstance(result, TissCourseInfo)
        assert result.course_number == "186.866"
        assert result.title_de == "Algorithmen und Datenstrukturen"
        assert result.ects == 6.0

    @respx.mock
    async def test_404_returns_empty_default(self, adapter: TissAdapter) -> None:
        respx.get(f"{HOST}/api/course/999999-2026S").mock(
            return_value=httpx.Response(404)
        )

        result = await adapter.get_course_details("999.999", "2026S")

        assert result.course_number == "999.999"
        assert result.semester == "2026S"
        assert result.title_de == ""

    @respx.mock
    async def test_500_raises_tiss_error(self, adapter: TissAdapter) -> None:
        respx.get(f"{HOST}/api/course/186866-2026S").mock(
            return_value=httpx.Response(500)
        )

        with pytest.raises(TissError, match="HTTP 500"):
            await adapter.get_course_details("186.866", "2026S")

    @respx.mock
    async def test_malformed_xml_raises_tiss_error(self, adapter: TissAdapter) -> None:
        respx.get(f"{HOST}/api/course/186866-2026S").mock(
            return_value=httpx.Response(200, text="<not valid xml")
        )

        with pytest.raises(TissError, match="Failed to parse"):
            await adapter.get_course_details("186.866", "2026S")


# ------------------------------------------------------------------
# TissAdapter.get_exam_dates
# ------------------------------------------------------------------


class TestGetExamDates:
    @respx.mock
    async def test_fetches_and_parses_exams(self, adapter: TissAdapter) -> None:
        respx.get(f"{HOST}/api/course/186866/examDates").mock(
            return_value=httpx.Response(200, text=EXAM_DATES_XML)
        )

        results = await adapter.get_exam_dates("186.866")

        assert len(results) == 2
        assert all(isinstance(r, TissExamDate) for r in results)
        assert results[0].title == "1. Prüfungstermin"

    @respx.mock
    async def test_404_returns_empty_list(self, adapter: TissAdapter) -> None:
        respx.get(f"{HOST}/api/course/999999/examDates").mock(
            return_value=httpx.Response(404)
        )

        results = await adapter.get_exam_dates("999.999")
        assert results == []

    @respx.mock
    async def test_500_raises_tiss_error(self, adapter: TissAdapter) -> None:
        respx.get(f"{HOST}/api/course/186866/examDates").mock(
            return_value=httpx.Response(500)
        )

        with pytest.raises(TissError, match="HTTP 500"):
            await adapter.get_exam_dates("186.866")

    @respx.mock
    async def test_empty_exam_list(self, adapter: TissAdapter) -> None:
        respx.get(f"{HOST}/api/course/186866/examDates").mock(
            return_value=httpx.Response(200, text=EMPTY_EXAM_DATES_XML)
        )

        results = await adapter.get_exam_dates("186.866")
        assert results == []


# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------


class TestProtocolConformance:
    def test_tiss_adapter_conforms_to_course_metadata_provider(
        self, adapter: TissAdapter
    ) -> None:
        assert _conforms_to(adapter, CourseMetadataProvider)
