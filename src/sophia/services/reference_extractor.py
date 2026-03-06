"""Multi-strategy book reference extraction from course content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from typing import assert_never

import isbnlib  # type: ignore[import-untyped]
import structlog
from bs4 import BeautifulSoup

from sophia.domain.errors import ExtractionError
from sophia.domain.models import BookReference, ReferenceSource

logger = structlog.get_logger()

# --- Constants ---

FUZZY_TITLE_THRESHOLD = 0.8

ISBN_REGEX = re.compile(
    r"(?:97[89][-\s]?\d[-\s]?\d{2,4}[-\s]?\d{1,7}[-\s]?\d{1,7}[-\s]?\d"
    r"|(?:\d[-\s]?){9}[\dXx])"
)

SECTION_HEADERS = {
    "literatur",
    "empfohlene bücher",
    "recommended reading",
    "required textbooks",
    "bibliography",
    "references",
    "pflichtliteratur",
    "weiterführende literatur",
}

HEADER_TAGS = {"h2", "h3", "h4", "strong", "b"}

# Block-level tags that signal the END of a literature section.
# Excludes inline formatting (strong, b) which appear inside list items.
SECTION_END_TAGS = {"h2", "h3", "h4"}

RESOURCE_NAME_RE = re.compile(
    r"^(?P<author>[A-Z][a-z]+(?:[A-Z][a-z]+)*)_(?P<title>[A-Z][A-Za-z]+(?:[A-Z][a-z]+)*).*\.\w+$"
)

GENERIC_PREFIXES = frozenset(
    {
        "slides",
        "lecture",
        "exercise",
        "tutorial",
        "homework",
        "assignment",
        "solution",
        "notes",
        "exam",
        "test",
        "quiz",
        "lab",
        "script",
        "summary",
        "overview",
        "introduction",
        "chapter",
        "ch",
        "vol",
        "part",
        "img",
        "image",
        "figure",
        "fig",
        "video",
        "audio",
        "template",
        "sample",
        "demo",
        "example",
    }
)


# --- Structural pattern-matching helpers ---


@dataclass(frozen=True, slots=True)
class HasISBN13:
    isbn: str


@dataclass(frozen=True, slots=True)
class HasISBN10:
    isbn: str


@dataclass(frozen=True, slots=True)
class HasTitleAndAuthor:
    title: str
    author: str


@dataclass(frozen=True, slots=True)
class HasBareTitle:
    title: str


type RawRef = HasISBN13 | HasISBN10 | HasTitleAndAuthor | HasBareTitle


# --- Extraction pipeline ---


def _strip_html(html_content: str) -> str:
    """Remove HTML tags and decode entities."""
    soup = BeautifulSoup(html_content, "lxml")
    return unescape(soup.get_text(separator=" ", strip=True))


def _extract_isbns(text: str) -> list[str]:
    """Extract and validate ISBNs using both regex and isbnlib."""
    candidates: set[str] = set()

    for match in ISBN_REGEX.findall(text):
        candidates.add(match)

    for candidate in isbnlib.get_isbnlike(text):  # type: ignore[no-untyped-call]
        candidates.add(str(candidate))  # pyright: ignore[reportUnknownArgumentType]

    valid: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        canonical: str = isbnlib.canonical(raw)  # type: ignore[no-untyped-call]
        if canonical in seen:
            continue
        if isbnlib.is_isbn13(canonical) or isbnlib.is_isbn10(canonical):  # type: ignore[no-untyped-call]
            seen.add(canonical)
            valid.append(canonical)

    return valid


def _classify_isbn(isbn: str) -> HasISBN13 | HasISBN10:
    """Classify a validated ISBN by length."""
    if isbnlib.is_isbn13(isbn):  # type: ignore[no-untyped-call]
        return HasISBN13(isbn=isbn)
    return HasISBN10(isbn=isbn)


def _extract_section_refs(html_content: str) -> list[HasBareTitle]:
    """Find literature section headers in HTML and extract list items after them."""
    soup = BeautifulSoup(html_content, "lxml")
    refs: list[HasBareTitle] = []

    for tag in soup.find_all(HEADER_TAGS):
        header_text = tag.get_text(strip=True).lower().rstrip(":")
        if header_text not in SECTION_HEADERS:
            continue

        # Walk siblings after the header looking for list items
        for sibling in tag.find_all_next():
            if sibling.name in SECTION_END_TAGS:
                break
            if sibling.name == "li":
                item_text = sibling.get_text(strip=True)
                if item_text:
                    refs.append(HasBareTitle(title=item_text))

    return refs


def _parse_resource_name(filename: str) -> HasTitleAndAuthor | None:
    """Parse 'Author_Title*.ext' filenames into references."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename

    # Skip generic resource names
    first_part = stem.split("_")[0].lower()
    if first_part in GENERIC_PREFIXES:
        return None

    match = RESOURCE_NAME_RE.match(filename)
    if not match:
        return None

    author = match.group("author")
    title = match.group("title")

    # Insert spaces before uppercase letters for CamelCase titles
    title = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", title)

    return HasTitleAndAuthor(title=title, author=author)


def _build_reference(
    raw: RawRef,
    source: ReferenceSource,
    course_id: int,
) -> BookReference:
    """Convert a raw extraction result into a BookReference using structural matching."""
    match raw:
        case HasISBN13(isbn=isbn):
            return BookReference(
                title="",
                isbn=isbn,
                source=source,
                course_id=course_id,
                confidence=0.95,
            )
        case HasISBN10(isbn=isbn):
            return BookReference(
                title="",
                isbn=isbn,
                source=source,
                course_id=course_id,
                confidence=0.9,
            )
        case HasTitleAndAuthor(title=title, author=author):
            return BookReference(
                title=title,
                authors=[author],
                source=source,
                course_id=course_id,
                confidence=0.6,
            )
        case HasBareTitle(title=title):
            return BookReference(
                title=title,
                source=source,
                course_id=course_id,
                confidence=0.5,
            )
        case unreachable:  # pyright: ignore[reportUnnecessaryComparison]
            assert_never(unreachable)


def _deduplicate(refs: list[BookReference]) -> list[BookReference]:
    """Merge duplicates: same ISBN collapses; fuzzy title match for ISBN-less refs."""
    by_isbn: dict[str, BookReference] = {}
    no_isbn: list[BookReference] = []

    for ref in refs:
        if ref.isbn:
            existing = by_isbn.get(ref.isbn)
            if existing:
                by_isbn[ref.isbn] = _merge_refs(existing, ref)
            else:
                by_isbn[ref.isbn] = ref
        else:
            no_isbn.append(ref)

    deduped_no_isbn = _deduplicate_by_title(no_isbn)
    return list(by_isbn.values()) + deduped_no_isbn


def _merge_refs(a: BookReference, b: BookReference) -> BookReference:
    """Merge two references, preferring the one with more information."""
    return BookReference(
        title=a.title or b.title,
        authors=a.authors if a.authors else b.authors,
        isbn=a.isbn or b.isbn,
        source=a.source,
        course_id=a.course_id,
        course_name=a.course_name or b.course_name,
        confidence=max(a.confidence, b.confidence),
    )


def _deduplicate_by_title(refs: list[BookReference]) -> list[BookReference]:
    """Fuzzy-match titles and merge near-duplicates."""
    if not refs:
        return []

    result: list[BookReference] = []
    used: set[int] = set()

    for i, ref in enumerate(refs):
        if i in used:
            continue
        merged = ref
        for j in range(i + 1, len(refs)):
            if j in used:
                continue
            ratio = SequenceMatcher(None, merged.title.lower(), refs[j].title.lower()).ratio()
            if ratio >= FUZZY_TITLE_THRESHOLD:
                merged = _merge_refs(merged, refs[j])
                used.add(j)
        result.append(merged)

    return result


class RegexReferenceExtractor:
    """Multi-strategy sync reference extractor (CPU-bound, no network calls).

    Implements the ReferenceExtractor protocol.
    """

    def extract(
        self,
        content: str,
        source: ReferenceSource,
        course_id: int,
    ) -> list[BookReference]:
        """Extract book references from HTML or plain-text content."""
        if not content or not content.strip():
            return []

        try:
            return self._run_pipeline(content, source, course_id)
        except ExtractionError:
            raise
        except Exception as exc:
            logger.error("extraction_failed", error=str(exc), source=source)
            raise ExtractionError(f"Reference extraction failed: {exc}") from exc

    def _run_pipeline(
        self,
        content: str,
        source: ReferenceSource,
        course_id: int,
    ) -> list[BookReference]:
        """Run all extraction strategies and deduplicate results."""
        raw_refs: list[RawRef] = []

        plain_text = _strip_html(content)

        # Strategy 1: ISBN extraction
        for isbn in _extract_isbns(plain_text):
            raw_refs.append(_classify_isbn(isbn))

        # Strategy 2: Section header detection
        raw_refs.extend(_extract_section_refs(content))

        # Strategy 3: Resource name parsing (only for resource_name source)
        if source == ReferenceSource.RESOURCE_NAME:
            parsed = _parse_resource_name(content)
            if parsed:
                raw_refs.append(parsed)

        refs = [_build_reference(raw, source, course_id) for raw in raw_refs]
        return _deduplicate(refs)
