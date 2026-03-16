"""Tests for the regex-based reference extractor."""

from __future__ import annotations

import isbnlib  # type: ignore[import-untyped]
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sophia.domain.errors import ExtractionError
from sophia.domain.models import BookReference, ReferenceSource
from sophia.domain.ports import ReferenceExtractor
from sophia.services.reference_extractor import (
    RegexReferenceExtractor,
    _deduplicate,  # pyright: ignore[reportPrivateUsage]
    _parse_resource_name,  # pyright: ignore[reportPrivateUsage]
    _strip_html,  # pyright: ignore[reportPrivateUsage]
)


@pytest.fixture
def extractor() -> RegexReferenceExtractor:
    return RegexReferenceExtractor()


SOURCE = ReferenceSource.DESCRIPTION
COURSE_ID = 42


# ------------------------------------------------------------------
# Structural conformance
# ------------------------------------------------------------------


def _conforms_to(instance: object, protocol: type) -> bool:
    """Check structural conformance without requiring @runtime_checkable."""
    hints = {
        name
        for name in dir(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }
    return all(callable(getattr(instance, name, None)) for name in hints)


class TestProtocolConformance:
    def test_implements_reference_extractor(self, extractor: RegexReferenceExtractor):
        assert _conforms_to(extractor, ReferenceExtractor)

    def test_extract_returns_list_of_book_references(self, extractor: RegexReferenceExtractor):
        result = extractor.extract("Some text", SOURCE, COURSE_ID)
        assert isinstance(result, list)


# ------------------------------------------------------------------
# ISBN extraction
# ------------------------------------------------------------------


class TestISBNExtraction:
    def test_isbn13_with_hyphens(self, extractor: RegexReferenceExtractor):
        text = "See: 978-0-201-63361-0 for details."
        refs = extractor.extract(text, SOURCE, COURSE_ID)
        assert len(refs) == 1
        assert refs[0].isbn == "9780201633610"

    def test_isbn13_without_hyphens(self, extractor: RegexReferenceExtractor):
        text = "ISBN 9780201633610."
        refs = extractor.extract(text, SOURCE, COURSE_ID)
        assert len(refs) == 1
        assert refs[0].isbn == "9780201633610"

    def test_isbn10_with_hyphens(self, extractor: RegexReferenceExtractor):
        text = "Book ISBN: 0-201-63361-2."
        refs = extractor.extract(text, SOURCE, COURSE_ID)
        assert len(refs) == 1
        assert refs[0].isbn == "0201633612"

    def test_isbn10_with_x_check_digit(self, extractor: RegexReferenceExtractor):
        text = "ISBN 155860832X is here."
        refs = extractor.extract(text, SOURCE, COURSE_ID)
        assert len(refs) == 1
        assert refs[0].isbn == "155860832X"

    def test_multiple_isbns_in_text(self, extractor: RegexReferenceExtractor):
        text = "Books: 978-0-201-63361-0 and 978-3-16-148410-0."
        refs = extractor.extract(text, SOURCE, COURSE_ID)
        isbns = {r.isbn for r in refs}
        assert "9780201633610" in isbns
        assert "9783161484100" in isbns

    def test_invalid_isbn_not_extracted(self, extractor: RegexReferenceExtractor):
        text = "Not an ISBN: 1234567890123."
        refs = extractor.extract(text, SOURCE, COURSE_ID)
        # Only valid ISBNs survive validation
        for ref in refs:
            if ref.isbn:
                assert isbnlib.is_isbn10(ref.isbn) or isbnlib.is_isbn13(ref.isbn)  # type: ignore[no-untyped-call]

    def test_isbn_sets_correct_source_and_course(self, extractor: RegexReferenceExtractor):
        text = "978-0-201-63361-0"
        refs = extractor.extract(text, SOURCE, COURSE_ID)
        assert refs[0].source == SOURCE
        assert refs[0].course_id == COURSE_ID

    def test_isbn13_has_higher_confidence_than_isbn10(self, extractor: RegexReferenceExtractor):
        text13 = "978-0-201-63361-0"
        text10 = "0-201-63361-2"
        refs13 = extractor.extract(text13, SOURCE, COURSE_ID)
        refs10 = extractor.extract(text10, SOURCE, COURSE_ID)
        assert refs13[0].confidence > refs10[0].confidence


# ------------------------------------------------------------------
# Section header detection
# ------------------------------------------------------------------


class TestSectionHeaderDetection:
    @pytest.mark.parametrize(
        "header",
        [
            "Literatur",
            "Empfohlene Bücher",
            "Pflichtliteratur",
            "Weiterführende Literatur",
        ],
    )
    def test_german_headers(self, extractor: RegexReferenceExtractor, header: str):
        html = f"<h3>{header}</h3><ul><li>Some Book Title, 2020</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1
        assert any("Some Book Title" in r.title for r in refs)

    @pytest.mark.parametrize(
        "header",
        [
            "Recommended Reading",
            "Required Textbooks",
            "Bibliography",
            "References",
        ],
    )
    def test_english_headers(self, extractor: RegexReferenceExtractor, header: str):
        html = f"<h3>{header}</h3><ul><li>Clean Code by Robert C. Martin</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1

    def test_ordered_list_after_header(self, extractor: RegexReferenceExtractor):
        html = """
        <h3>Literatur</h3>
        <ol>
            <li>Tanenbaum, A. S. Distributed Systems. Pearson, 2017.</li>
            <li>Coulouris et al. Distributed Systems. Addison-Wesley, 2011.</li>
        </ol>
        """
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 2

    def test_h2_header_tag(self, extractor: RegexReferenceExtractor):
        html = "<h2>References</h2><ul><li>A Book</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1

    def test_h4_header_tag(self, extractor: RegexReferenceExtractor):
        html = "<h4>Bibliography</h4><ul><li>Another Book</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1

    def test_strong_header_tag(self, extractor: RegexReferenceExtractor):
        html = "<strong>Literatur</strong><ul><li>Ein Buch</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1

    def test_bold_header_tag(self, extractor: RegexReferenceExtractor):
        html = "<b>References</b><ul><li>The Book</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1

    def test_header_with_colon(self, extractor: RegexReferenceExtractor):
        html = "<h3>Literatur:</h3><ul><li>Ein Buch</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1

    def test_book_entry_format(self, extractor: RegexReferenceExtractor):
        html = """
        <h3>References</h3>
        <ul><li>Martin, Robert C. Clean Architecture. Prentice Hall, 2017.</li></ul>
        """
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1
        assert "Clean Architecture" in refs[0].title

    def test_stops_at_next_header(self, extractor: RegexReferenceExtractor):
        html = """
        <h3>References</h3>
        <ul><li>Real Book</li></ul>
        <h3>Contact</h3>
        <ul><li>prof@example.com</li></ul>
        """
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        titles = [r.title for r in refs]
        assert "Real Book" in titles
        assert "prof@example.com" not in titles

    def test_bold_inside_list_items_not_truncated(self, extractor: RegexReferenceExtractor):
        """Inline <strong>/<b> inside list items must not end the section."""
        html = """
        <h3>Literatur</h3>
        <ul>
            <li><strong>Tanenbaum:</strong> Distributed Systems</li>
            <li>Coulouris: Another Book</li>
        </ul>
        """
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        titles = [r.title for r in refs]
        assert len(refs) >= 2
        assert any("Another Book" in t for t in titles)

    def test_bibliography_line_without_isbn_extracts_author_and_title(
        self, extractor: RegexReferenceExtractor
    ):
        html = """
        <h3>Literatur</h3>
        <ul>
            <li>Tanenbaum, Andrew S.: Modern Operating Systems. Pearson, 2014.</li>
        </ul>
        """
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        ref = next(r for r in refs if "Modern Operating Systems" in r.title)
        assert ref.authors == ["Tanenbaum, Andrew S"]
        assert ref.confidence == 0.6

    def test_uncertain_bibliography_line_falls_back_to_bare_title(
        self, extractor: RegexReferenceExtractor
    ):
        html = """
        <h3>Bibliography</h3>
        <ul>
            <li>Modern Operating Systems overview notes</li>
        </ul>
        """
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) == 1
        assert refs[0].title == "Modern Operating Systems overview notes"
        assert refs[0].authors == []
        assert refs[0].confidence == 0.5

    @pytest.mark.parametrize(
        "bullet",
        [
            "TODO: submit assignment 2 by Friday",
            "Task: submit assignment 2 by Friday",
            "Contact: prof@example.com",
            "https://example.com/reading-list",
        ],
    )
    def test_non_bibliography_task_or_link_bullets_are_ignored(
        self,
        extractor: RegexReferenceExtractor,
        bullet: str,
    ):
        html = f"<h3>References</h3><ul><li>{bullet}</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert refs == []

    @pytest.mark.parametrize(
        "line",
        [
            "Task: A Practical Introduction to Research. Springer, 2021.",
            "Exercise: Theory and Practice. Springer, 2021.",
            "Contact: A Philosophical Study. Springer, 2021.",
            "Link: An Essay on Meaning. Springer, 2021.",
            "Task - A Practical Introduction to Research. Springer, 2021.",
        ],
    )
    def test_legitimate_prefixed_bibliography_lines_are_preserved(
        self,
        extractor: RegexReferenceExtractor,
        line: str,
    ):
        html = f"<h3>Bibliography</h3><ul><li>{line}</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) == 1
        assert refs[0].title == line.rsplit(".", maxsplit=2)[0]

    @pytest.mark.parametrize(
        "title",
        [
            "Task Analysis in Human-Computer Interaction",
            "Link Prediction in Complex Networks",
            "Exercise Physiology Fundamentals",
            "Contact Mechanics",
        ],
    )
    def test_legitimate_titles_with_guard_prefixes_are_preserved(
        self,
        extractor: RegexReferenceExtractor,
        title: str,
    ):
        html = f"<h3>Bibliography</h3><ul><li>{title}. Springer, 2021.</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) == 1
        assert refs[0].title == title

    @pytest.mark.parametrize(
        ("line", "author", "title"),
        [
            (
                "Tanenbaum, A. S. Distributed Systems. Pearson, 2017.",
                "Tanenbaum, A. S",
                "Distributed Systems",
            ),
            (
                "Knuth, D. E. The Art of Computer Programming. Addison-Wesley, 1968.",
                "Knuth, D. E",
                "The Art of Computer Programming",
            ),
        ],
    )
    def test_bibliography_line_with_spaced_initials_extracts_author_and_title(
        self,
        extractor: RegexReferenceExtractor,
        line: str,
        author: str,
        title: str,
    ):
        html = f"<h3>Literatur</h3><ul><li>{line}</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        ref = next(r for r in refs if r.title == title)
        assert ref.authors == [author]
        assert ref.confidence == 0.6

    def test_isbn_extraction_regression_with_bibliography_line(
        self, extractor: RegexReferenceExtractor
    ):
        html = """
        <div>
            <p>Textbook ISBN: 978-0-201-63361-0</p>
            <h3>References</h3>
            <ul>
                <li>Gamma, Erich: Design Patterns. Addison-Wesley, 1995.</li>
            </ul>
        </div>
        """
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert any(r.isbn == "9780201633610" for r in refs)
        assert any(r.title == "Design Patterns" and r.authors == ["Gamma, Erich"] for r in refs)


# ------------------------------------------------------------------
# Resource name parsing
# ------------------------------------------------------------------


class TestResourceNameParsing:
    def test_author_title_pattern(self, extractor: RegexReferenceExtractor):
        refs = extractor.extract(
            "Tanenbaum_DistributedSystems_Ch3.pdf",
            ReferenceSource.RESOURCE_NAME,
            COURSE_ID,
        )
        assert len(refs) >= 1
        ref = refs[0]
        assert "Distributed" in ref.title or "DistributedSystems" in ref.title
        assert "Tanenbaum" in ref.authors

    def test_generic_resource_not_extracted(self, extractor: RegexReferenceExtractor):
        refs = extractor.extract(
            "slides_lecture01.pdf",
            ReferenceSource.RESOURCE_NAME,
            COURSE_ID,
        )
        assert len(refs) == 0

    def test_notes_not_extracted(self, extractor: RegexReferenceExtractor):
        refs = extractor.extract(
            "notes_week3.pdf",
            ReferenceSource.RESOURCE_NAME,
            COURSE_ID,
        )
        assert len(refs) == 0

    def test_resource_parsing_only_for_resource_name_source(
        self, extractor: RegexReferenceExtractor
    ):
        """Resource name parsing only activates for RESOURCE_NAME source."""
        refs = extractor.extract(
            "Tanenbaum_DistributedSystems_Ch3.pdf",
            ReferenceSource.DESCRIPTION,
            COURSE_ID,
        )
        # Should not produce a resource-name-parsed ref from description source
        assert all("Tanenbaum" not in r.authors for r in refs)

    def test_camel_case_title_spacing(self):
        result = _parse_resource_name("Knuth_TheArtOfProgramming.pdf")
        assert result is not None
        assert "Art" in result.title
        assert result.author == "Knuth"


# ------------------------------------------------------------------
# HTML handling
# ------------------------------------------------------------------


class TestHTMLHandling:
    def test_html_entities_decoded(self):
        plain = _strip_html("Smith &amp; Jones&#39;s Book")
        assert "Smith & Jones's Book" in plain

    def test_nested_html_tags_stripped(self):
        plain = _strip_html("<div><p><em>Hello</em> <strong>World</strong></p></div>")
        assert "Hello" in plain
        assert "World" in plain
        assert "<" not in plain

    def test_empty_input_returns_empty_list(self, extractor: RegexReferenceExtractor):
        assert extractor.extract("", SOURCE, COURSE_ID) == []

    def test_whitespace_only_returns_empty_list(self, extractor: RegexReferenceExtractor):
        assert extractor.extract("   \n\t  ", SOURCE, COURSE_ID) == []

    def test_html_with_no_book_content(self, extractor: RegexReferenceExtractor):
        html = "<div><p>Welcome to the course!</p><p>Schedule: Monday 10am</p></div>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert refs == []

    def test_malformed_html(self, extractor: RegexReferenceExtractor):
        html = "<div><p>Unclosed tag <b>bold text<ul><li>item</div>"
        # Should not crash
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert isinstance(refs, list)


# ------------------------------------------------------------------
# Deduplication
# ------------------------------------------------------------------


class TestDeduplication:
    def test_same_isbn_merged(self, extractor: RegexReferenceExtractor):
        html = "ISBN: 978-0-201-63361-0. Also see 978-0-201-63361-0."
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        isbn_refs = [r for r in refs if r.isbn == "9780201633610"]
        assert len(isbn_refs) == 1

    def test_similar_titles_deduplicated(self):
        refs = [
            BookReference(
                title="Clean Architecture",
                source=SOURCE,
                course_id=COURSE_ID,
                confidence=0.5,
            ),
            BookReference(
                title="Clean Architecture: A Guide",
                source=SOURCE,
                course_id=COURSE_ID,
                confidence=0.5,
            ),
        ]
        deduped = _deduplicate(refs)
        assert len(deduped) == 1

    def test_dissimilar_titles_kept_separate(self):
        refs = [
            BookReference(
                title="Clean Architecture",
                source=SOURCE,
                course_id=COURSE_ID,
            ),
            BookReference(
                title="Design Patterns",
                source=SOURCE,
                course_id=COURSE_ID,
            ),
        ]
        deduped = _deduplicate(refs)
        assert len(deduped) == 2

    def test_same_title_with_different_authors_is_not_deduplicated(self):
        refs = [
            BookReference(
                title="Distributed Systems",
                authors=["Tanenbaum, A. S"],
                source=SOURCE,
                course_id=COURSE_ID,
                confidence=0.6,
            ),
            BookReference(
                title="Distributed Systems",
                authors=["Coulouris et al"],
                source=SOURCE,
                course_id=COURSE_ID,
                confidence=0.6,
            ),
        ]
        deduped = _deduplicate(refs)
        assert len(deduped) == 2

    def test_merge_prefers_more_info(self):
        refs = [
            BookReference(
                title="",
                isbn="9780201633610",
                source=SOURCE,
                course_id=COURSE_ID,
                confidence=0.9,
            ),
            BookReference(
                title="The Pragmatic Programmer",
                isbn="9780201633610",
                source=SOURCE,
                course_id=COURSE_ID,
                confidence=0.5,
                authors=["Hunt", "Thomas"],
            ),
        ]
        deduped = _deduplicate(refs)
        assert len(deduped) == 1
        merged = deduped[0]
        assert merged.title == "The Pragmatic Programmer"
        assert merged.authors == ["Hunt", "Thomas"]
        assert merged.confidence == 0.9


# ------------------------------------------------------------------
# Hypothesis property-based tests
# ------------------------------------------------------------------


class TestPropertyBased:
    @given(st.text())
    @settings(max_examples=10000)
    def test_never_crashes_on_random_input(self, text: str):
        extractor = RegexReferenceExtractor()
        result = extractor.extract(text, SOURCE, COURSE_ID)
        assert isinstance(result, list)
        assert all(isinstance(r, BookReference) for r in result)

    @given(st.text(min_size=0, max_size=5))
    @settings(max_examples=100)
    def test_short_input_returns_list(self, text: str):
        extractor = RegexReferenceExtractor()
        result = extractor.extract(text, SOURCE, COURSE_ID)
        assert isinstance(result, list)


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


class TestEdgeCases:
    def test_very_long_input(self, extractor: RegexReferenceExtractor):
        long_text = "No books here. " * 10_000
        refs = extractor.extract(long_text, SOURCE, COURSE_ID)
        assert isinstance(refs, list)

    def test_isbn_embedded_in_html(self, extractor: RegexReferenceExtractor):
        html = "<p>Textbook ISBN: <code>978-0-13-468599-1</code></p>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1

    def test_mixed_strategies_combined(self, extractor: RegexReferenceExtractor):
        html = """
        <div>
            <p>Recommended ISBN: 978-0-201-63361-0</p>
            <h3>Literatur</h3>
            <ul><li>Gamma et al. Design Patterns. Addison-Wesley, 1995.</li></ul>
        </div>
        """
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 2

    def test_only_whitespace_in_html_tags(self, extractor: RegexReferenceExtractor):
        html = "<div>   </div><p>\n\t</p>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert refs == []

    def test_unicode_content(self, extractor: RegexReferenceExtractor):
        html = "<h3>Literatur</h3><ul><li>Müller, Einführung in die Informatik</li></ul>"
        refs = extractor.extract(html, SOURCE, COURSE_ID)
        assert len(refs) >= 1

    def test_extraction_error_wraps_unexpected_exception(
        self, extractor: RegexReferenceExtractor, monkeypatch: pytest.MonkeyPatch
    ):
        """Unexpected exceptions are wrapped in ExtractionError."""

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("parser exploded")

        monkeypatch.setattr("sophia.services.reference_extractor._strip_html", _boom)
        with pytest.raises(ExtractionError, match="parser exploded"):
            extractor.extract("some content", SOURCE, COURSE_ID)
