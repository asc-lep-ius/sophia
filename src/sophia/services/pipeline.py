"""Discovery pipeline — fetches courses, extracts book references, deduplicates."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

import structlog

from sophia.adapters.tiss import resolve_course_info
from sophia.domain.events import ExtractionReport
from sophia.domain.models import BookReference, CourseSection, ModuleInfo, ReferenceSource
from sophia.services.resource_classifier import classify_modules, is_book_resource

if TYPE_CHECKING:
    import aiosqlite

    from sophia.domain.ports import (
        CourseMetadataProvider,
        CourseProvider,
        ReferenceExtractor,
        ResourceProvider,
    )

logger = structlog.get_logger()

# Similarity threshold for fuzzy title deduplication across courses
FUZZY_TITLE_THRESHOLD = 0.8

type EventCallback = Callable[[Any], None]

# Internal result from per-course processing: either refs or an error message
type _CourseResult = tuple[str, list[BookReference] | str]
type _ResourceExtractionResult = tuple[list[BookReference], list[ModuleInfo] | None]


async def discover_books(
    courses: CourseProvider,
    resources: ResourceProvider,
    extractor: ReferenceExtractor,
    on_event: EventCallback | None = None,
    metadata: CourseMetadataProvider | None = None,
) -> list[BookReference]:
    """Fetch enrolled courses, extract book references, and return deduplicated results.

    Processes courses concurrently via TaskGroup. Per-course errors are collected
    rather than aborting the whole pipeline.
    """
    enrolled = await courses.get_enrolled_courses()
    logger.info("courses_fetched", count=len(enrolled))

    results: list[_CourseResult] = []

    async with asyncio.TaskGroup() as tg:
        for course in enrolled:
            tg.create_task(
                _safe_process_course(
                    course.id,
                    course.fullname,
                    course.shortname,
                    courses,
                    resources,
                    extractor,
                    results,
                    metadata=metadata,
                ),
            )

    all_refs: list[BookReference] = []
    failed: list[tuple[str, str]] = []
    for course_name, outcome in results:
        if isinstance(outcome, str):
            failed.append((course_name, outcome))
        else:
            all_refs.extend(outcome)

    deduped = _deduplicate_across_courses(all_refs)
    successful = len(enrolled) - len(failed)

    report = ExtractionReport(
        total_courses=len(enrolled),
        successful=successful,
        failed=failed,
        total_references=len(deduped),
    )
    if on_event:
        on_event(report)

    logger.info(
        "discovery_complete",
        total_courses=len(enrolled),
        successful=successful,
        failed=len(failed),
        references=len(deduped),
    )
    return deduped


async def _safe_process_course(
    course_id: int,
    course_name: str,
    course_shortname: str,
    courses: CourseProvider,
    resources: ResourceProvider,
    extractor: ReferenceExtractor,
    results: list[_CourseResult],
    *,
    metadata: CourseMetadataProvider | None = None,
) -> None:
    """Wrapper that catches per-course errors so TaskGroup doesn't abort."""
    try:
        refs = await _process_course(
            course_id,
            course_name,
            course_shortname,
            courses,
            resources,
            extractor,
            metadata=metadata,
        )
        results.append((course_name, refs))
    except Exception as exc:  # noqa: BLE001
        logger.warning("course_failed", course=course_name, error=str(exc))
        results.append((course_name, str(exc)))


async def _process_course(
    course_id: int,
    course_name: str,
    course_shortname: str,
    courses: CourseProvider,
    resources: ResourceProvider,
    extractor: ReferenceExtractor,
    *,
    metadata: CourseMetadataProvider | None = None,
) -> list[BookReference]:
    """Extract references from all content sources for a single course.

    Section content (core_course_get_contents) is the primary source — always
    available via the AJAX API. The mod_* resource calls are best-effort: they
    may not be exposed on all Moodle instances (e.g. behind the WS-only API).
    TISS teaching content and URL classification are additional sources.
    """
    logger.debug("processing_course", course=course_name, course_id=course_id)

    refs: list[BookReference] = []

    # Primary: always available via AJAX API
    sections = await courses.get_course_content(course_id)
    refs.extend(_extract_from_sections(sections, extractor, course_id))

    # Best-effort: mod_* functions may not be available via AJAX
    resource_refs, url_modules = await _try_resource_extraction(course_id, resources, extractor)
    refs.extend(resource_refs)

    # TISS teaching content: description + objectives as additional reference source
    tiss_refs = await _try_tiss_extraction(
        course_shortname,
        course_name,
        course_id,
        metadata,
        extractor,
    )
    refs.extend(tiss_refs)

    # URL classification prefers enriched mod/url results and falls back to section scraping.
    if url_modules is None:
        url_modules = _section_url_modules(sections)
    url_refs = _extract_from_url_modules(url_modules, extractor, course_id, course_name)
    refs.extend(url_refs)

    enriched = [ref.model_copy(update={"course_name": course_name}) for ref in refs]
    logger.debug("course_refs_found", course=course_name, count=len(enriched))
    return enriched


async def _try_resource_extraction(
    course_id: int,
    resources: ResourceProvider,
    extractor: ReferenceExtractor,
) -> _ResourceExtractionResult:
    """Attempt to fetch resources via mod_* API calls (best-effort).

    These web service functions may not be available via the AJAX endpoint
    on all Moodle instances. Failures are logged and silently skipped.
    """
    results = await asyncio.gather(
        resources.get_course_books([course_id]),
        resources.get_course_pages([course_id]),
        resources.get_course_resources([course_id]),
        resources.get_course_urls([course_id]),
        return_exceptions=True,
    )

    sources = [ReferenceSource.RESOURCE_NAME, ReferenceSource.PAGE, ReferenceSource.RESOURCE_NAME]
    refs: list[BookReference] = []

    for result, source in zip(results[:3], sources, strict=True):
        if isinstance(result, BaseException):
            logger.debug(
                "resource_fetch_skipped",
                course_id=course_id,
                source=source,
                error=str(result),
            )
            continue
        refs.extend(_extract_from_modules(result, extractor, course_id, source))

    url_result = results[3]
    if isinstance(url_result, BaseException):
        logger.debug(
            "resource_fetch_skipped",
            course_id=course_id,
            source="url",
            error=str(url_result),
        )
        return refs, None

    return refs, url_result


async def _try_tiss_extraction(
    course_shortname: str,
    course_fullname: str,
    course_id: int,
    metadata: CourseMetadataProvider | None,
    extractor: ReferenceExtractor,
) -> list[BookReference]:
    """Extract references from TISS teaching content (best-effort).

    Resolves course number + semester from TUWEL shortname/fullname metadata,
    then fetches TISS course details. Description and objectives are fed to
    the extractor.
    """
    if metadata is None:
        return []

    info = resolve_course_info(course_shortname, course_fullname)
    if info is None:
        logger.debug(
            "tiss_course_info_unresolved",
            shortname=course_shortname,
            fullname=course_fullname,
        )
        return []

    course_number, semester = info
    try:
        tiss_info = await metadata.get_course_details(course_number, semester)
    except Exception:  # noqa: BLE001
        logger.debug("tiss_fetch_failed", course_number=course_number, semester=semester)
        return []

    refs: list[BookReference] = []
    for text in (tiss_info.description_de, tiss_info.objectives_de):
        if text:
            refs.extend(extractor.extract(text, ReferenceSource.TISS, course_id))

    if refs:
        logger.debug("tiss_refs_found", course_number=course_number, count=len(refs))
    return refs


def _extract_from_url_modules(
    url_modules: list[ModuleInfo],
    extractor: ReferenceExtractor,
    course_id: int,
    course_name: str,
) -> list[BookReference]:
    """Classify URL modules from course sections and extract book references.

    URL modules classified as books have their names/descriptions fed to the
    extractor. Non-book resources are logged for future surfacing.
    """
    if not url_modules:
        return []

    classified = classify_modules(url_modules, course_id, course_name)
    book_resources = [r for r in classified if is_book_resource(r)]
    non_book_count = len(classified) - len(book_resources)

    if non_book_count:
        logger.debug(
            "url_non_book_resources",
            course_id=course_id,
            count=non_book_count,
        )

    refs: list[BookReference] = []
    for resource in book_resources:
        if resource.title:
            refs.extend(extractor.extract(resource.title, ReferenceSource.RESOURCE_NAME, course_id))

    for resource in classified:
        if resource.description:
            refs.extend(
                extractor.extract(resource.description, ReferenceSource.DESCRIPTION, course_id)
            )

    return refs


def _section_url_modules(sections: list[CourseSection]) -> list[ModuleInfo]:
    return [module for section in sections for module in section.modules if module.modname == "url"]


def _extract_from_sections(
    sections: list[CourseSection],
    extractor: ReferenceExtractor,
    course_id: int,
) -> list[BookReference]:
    """Extract references from course section content.

    Combines all HTML content within a section (summary + module descriptions)
    so header+list patterns can match even when split across separate label activities.
    Module names are still extracted individually as short identifiers.
    """
    refs: list[BookReference] = []
    for section in sections:
        combined_html_parts: list[str] = []
        if section.summary:
            combined_html_parts.append(section.summary)
        for module in section.modules:
            if module.description:
                combined_html_parts.append(module.description)
        if combined_html_parts:
            combined = "\n".join(combined_html_parts)
            refs.extend(extractor.extract(combined, ReferenceSource.DESCRIPTION, course_id))
        for module in section.modules:
            if module.name:
                refs.extend(
                    extractor.extract(module.name, ReferenceSource.RESOURCE_NAME, course_id)
                )
    return refs


def _extract_from_modules(
    modules: list[ModuleInfo],
    extractor: ReferenceExtractor,
    course_id: int,
    source: ReferenceSource,
) -> list[BookReference]:
    """Extract references from module names."""
    refs: list[BookReference] = []
    for module in modules:
        if module.name:
            refs.extend(extractor.extract(module.name, source, course_id))
        if module.description and _is_pdf_module(module):
            refs.extend(extractor.extract(module.description, ReferenceSource.PDF, course_id))
    return refs


def _is_pdf_module(module: ModuleInfo) -> bool:
    return any(
        content.mimetype == "application/pdf" or content.filename.lower().endswith(".pdf")
        for content in module.contents
    )


# --- Cross-course deduplication ---


def _deduplicate_across_courses(refs: list[BookReference]) -> list[BookReference]:
    """Deduplicate references across courses by ISBN or fuzzy title match."""
    if not refs:
        return []

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
    """Merge two references, preserving the richer entry."""
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
    """Fuzzy-match titles across courses and merge near-duplicates."""
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


# --- Persistence ---


async def persist_references(
    db: aiosqlite.Connection,
    refs: list[BookReference],
) -> int:
    """Persist discovered references to SQLite. Returns count of new/updated rows."""
    import json

    count = 0
    for ref in refs:
        result = await db.execute(
            "INSERT INTO discovered_references"
            " (title, authors, isbn, source, course_id, course_name, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(title, course_id, source) DO UPDATE SET"
            " authors = excluded.authors,"
            " isbn = COALESCE(excluded.isbn, discovered_references.isbn),"
            " confidence = MAX(excluded.confidence, discovered_references.confidence),"
            " course_name = COALESCE("
            "   NULLIF(excluded.course_name, ''), discovered_references.course_name),"
            " discovered_at = CURRENT_TIMESTAMP",
            (
                ref.title,
                json.dumps(ref.authors),
                ref.isbn,
                ref.source.value,
                ref.course_id,
                ref.course_name,
                ref.confidence,
            ),
        )
        if result.rowcount:
            count += result.rowcount
    await db.commit()
    return count


async def get_course_references(
    db: aiosqlite.Connection,
    *,
    course_id: int | None = None,
    course_name: str | None = None,
) -> list[BookReference]:
    """Load persisted references filtered by course_id or course_name."""
    import json

    query = (
        "SELECT title, authors, isbn, source, course_id, course_name, confidence "
        "FROM discovered_references"
    )
    params: tuple[int | str, ...] = ()

    if course_id is not None:
        query += " WHERE course_id = ?"
        params = (course_id,)
    elif course_name is not None:
        query += " WHERE course_name LIKE ?"
        params = (f"%{course_name}%",)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [
        BookReference(
            title=row[0],
            authors=json.loads(row[1]),
            isbn=row[2],
            source=ReferenceSource(row[3]),
            course_id=row[4],
            course_name=row[5],
            confidence=row[6],
        )
        for row in rows
    ]
