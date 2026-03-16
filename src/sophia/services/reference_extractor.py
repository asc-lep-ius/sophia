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

NON_BIBLIO_BULLET_PREFIXES = frozenset(
    {
        "todo",
        "task",
        "assignment",
        "exercise",
        "deadline",
        "submit",
        "contact",
        "email",
        "link",
        "abgabe",
        "aufgabe",
    }
)

NON_BIBLIO_BULLET_PATTERNS = (
    re.compile(r"^(?:todo|assignment|deadline|submit|abgabe|aufgabe)\s*(?::|-|\d\b)"),
    re.compile(r"^email\s*[:\-]"),
)

GUARDED_NON_BIBLIO_PREFIX_RE = re.compile(
    r"^(?P<prefix>task|exercise|contact|link)\s*(?P<separator>:|-)\s*(?P<remainder>.+)$",
    re.IGNORECASE,
)

NUMBERED_TASK_STRUCTURE_RE = re.compile(
    r"^(?P<prefix>task|exercise)\s+(?P<label>\(?\d+\)?|[ivxlcdm]+|[a-z])\s*(?P<separator>[.):-]|:)\s*(?P<remainder>.+)$",
    re.IGNORECASE,
)

ADMIN_REMAINDER_PATTERNS = (
    re.compile(r"^(?:submit|read|watch|complete|solve|prepare|review|visit|open|download|upload|contact|email)\b"),
    re.compile(r"\b(?:due|deadline|submission|submit|abgabe|einreichen|upload(?:ed)?|hand\s+in)\b"),
    re.compile(r"^(?:assignment|worksheet|slides?|lecture slides|forum|moodle|canvas|portal)\b"),
    re.compile(r"^(?:\(?\d+\)?|[ivxlcdm]+|[a-z])[.):-]\s+"),
)

URL_OR_EMAIL_RE = re.compile(
    r"(?:https?://|www\.|mailto:|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b)",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


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


def _normalize_section_item(item_text: str) -> str:
    """Normalize list-item text for bibliography parsing."""
    return re.sub(r"\s+", " ", item_text).strip()


def _looks_like_admin_remainder(item_text: str) -> bool:
    """Return whether a guarded bullet remainder looks administrative."""
    normalized = _normalize_section_item(item_text)
    if not normalized:
        return True
    if URL_OR_EMAIL_RE.search(normalized):
        return True
    lowered = normalized.lower()
    return any(pattern.search(lowered) for pattern in ADMIN_REMAINDER_PATTERNS)


def _matches_guarded_non_bibliography_prefix(item_text: str) -> bool:
    """Match guarded task-like prefixes only when the remainder is administrative."""
    normalized = _normalize_section_item(item_text)
    numbered_match = NUMBERED_TASK_STRUCTURE_RE.match(normalized)
    if numbered_match:
        return _looks_like_admin_remainder(numbered_match.group("remainder"))

    match = GUARDED_NON_BIBLIO_PREFIX_RE.match(normalized)
    if not match:
        return False

    return _looks_like_admin_remainder(match.group("remainder"))


def _is_non_bibliography_line(item_text: str) -> bool:
    """Reject obvious non-bibliography bullets in literature-like sections."""
    normalized = _normalize_section_item(item_text)
    if not normalized:
        return True
    if URL_OR_EMAIL_RE.search(normalized):
        return True
    if any(pattern.match(normalized.lower()) for pattern in NON_BIBLIO_BULLET_PATTERNS):
        return True
    return _matches_guarded_non_bibliography_prefix(normalized)


def _looks_like_author(author_candidate: str) -> bool:
    """Check whether a prefix resembles an author string."""
    author = author_candidate.strip(" ,;:-.")
    if len(author) < 4 or re.search(r"\d", author):
        return False

    lowered = author.lower()
    if any(lowered.startswith(prefix) for prefix in NON_BIBLIO_BULLET_PREFIXES):
        return False

    if "," in author or " et al" in lowered:
        return True

    words = [word for word in author.split() if word]
    if len(words) < 2:
        return False

    capitalized_words = sum(
        1
        for word in words
        if re.match(r"^[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’-]*\.?$", word)
    )
    return capitalized_words >= 2


def _looks_like_title(title_candidate: str) -> bool:
    """Check whether a segment resembles a plausible title."""
    title = title_candidate.strip(" ,;:-.")
    if len(title) < 6:
        return False
    if URL_OR_EMAIL_RE.search(title):
        return False
    words = re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'’-]*", title)
    return len(words) >= 2


def _extract_title_segment(segment_text: str) -> str:
    """Extract the likely title segment from a bibliography remainder."""
    first_sentence = re.split(r"\.\s+", segment_text, maxsplit=1)[0]
    cleaned = first_sentence.strip(" ,;:-.")
    if YEAR_RE.fullmatch(cleaned):
        return ""
    return cleaned


def _split_bibliography_sentences(item_text: str) -> list[str]:
    """Split bibliography lines into sentence-like parts while preserving content."""
    return [
        part.strip(" ,;:-.")
        for part in re.split(r"\.\s+", item_text)
        if part.strip(" ,;:-.")
    ]


def _is_initial_fragment(part: str) -> bool:
    """Return whether a sentence fragment is just an author initial."""
    return bool(re.fullmatch(r"[A-ZÄÖÜ]", part.strip()))


def _extract_author_and_title_from_sentences(
    sentence_parts: list[str],
) -> tuple[str, str] | None:
    """Reconstruct author/title pairs from bibliography sentence fragments."""
    if len(sentence_parts) < 2:
        return None

    author_parts = [sentence_parts[0]]
    title_index = 1

    if "," in sentence_parts[0]:
        while title_index < len(sentence_parts) and _is_initial_fragment(
            sentence_parts[title_index]
        ):
            author_parts.append(sentence_parts[title_index])
            title_index += 1

    if title_index >= len(sentence_parts):
        return None

    author = ". ".join(author_parts)
    title = sentence_parts[title_index]
    return author, title


def _parse_section_item(item_text: str) -> HasTitleAndAuthor | HasBareTitle | None:
    """Parse a literature section list item into a conservative reference signal."""
    normalized = _normalize_section_item(item_text)
    if _is_non_bibliography_line(normalized):
        return None

    colon_match = re.match(r"^(?P<author>[^:]{3,120}):\s*(?P<rest>.+)$", normalized)
    if colon_match:
        author = colon_match.group("author").strip(" ,;:-.")
        rest = colon_match.group("rest")
        title = _extract_title_segment(rest)
        if _looks_like_author(author) and _looks_like_title(title):
            return HasTitleAndAuthor(title=title, author=author)

    sentence_parts = _split_bibliography_sentences(normalized)
    author_and_title = _extract_author_and_title_from_sentences(sentence_parts)
    if author_and_title:
        author, title = author_and_title
        if _looks_like_author(author) and _looks_like_title(title):
            return HasTitleAndAuthor(title=title, author=author)

    if len(sentence_parts) >= 2:
        author = sentence_parts[0]
        title = sentence_parts[1]
        if _looks_like_author(author) and _looks_like_title(title):
            return HasTitleAndAuthor(title=title, author=author)

    bare_title = _extract_title_segment(normalized)
    if _looks_like_title(bare_title) and not _looks_like_author(bare_title):
        return HasBareTitle(title=bare_title)

    return HasBareTitle(title=normalized)


def _extract_section_refs(html_content: str) -> list[HasBareTitle | HasTitleAndAuthor]:
    """Find literature section headers in HTML and extract bibliography-like list items."""
    soup = BeautifulSoup(html_content, "lxml")
    refs: list[HasBareTitle | HasTitleAndAuthor] = []

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
                parsed = _parse_section_item(item_text)
                if parsed:
                    refs.append(parsed)

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


def _authors_conflict(a: BookReference, b: BookReference) -> bool:
    """Return whether two references carry incompatible author signals."""
    return bool(a.authors and b.authors and a.authors != b.authors)


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
            if _authors_conflict(merged, refs[j]):
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
