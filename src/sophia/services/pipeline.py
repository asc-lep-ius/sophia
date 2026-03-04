"""Discovery pipeline — fetches courses, extracts book references, deduplicates."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.events import ExtractionReport
from sophia.domain.models import BookReference, CourseSection, ModuleInfo, ReferenceSource

if TYPE_CHECKING:
    from sophia.domain.ports import CourseProvider, ReferenceExtractor, ResourceProvider

logger = structlog.get_logger()

# Similarity threshold for fuzzy title deduplication across courses
FUZZY_TITLE_THRESHOLD = 0.8

type EventCallback = Callable[[Any], None]

# Internal result from per-course processing: either refs or an error message
type _CourseResult = tuple[str, list[BookReference] | str]


async def discover_books(
    courses: CourseProvider,
    resources: ResourceProvider,
    extractor: ReferenceExtractor,
    on_event: EventCallback | None = None,
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
                    course.id, course.fullname, courses, resources, extractor, results
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
    courses: CourseProvider,
    resources: ResourceProvider,
    extractor: ReferenceExtractor,
    results: list[_CourseResult],
) -> None:
    """Wrapper that catches per-course errors so TaskGroup doesn't abort."""
    try:
        refs = await _process_course(course_id, course_name, courses, resources, extractor)
        results.append((course_name, refs))
    except Exception as exc:  # noqa: BLE001
        logger.warning("course_failed", course=course_name, error=str(exc))
        results.append((course_name, str(exc)))


async def _process_course(
    course_id: int,
    course_name: str,
    courses: CourseProvider,
    resources: ResourceProvider,
    extractor: ReferenceExtractor,
) -> list[BookReference]:
    """Extract references from all content sources for a single course.

    Section content (core_course_get_contents) is the primary source — always
    available via the AJAX API. The mod_* resource calls are best-effort: they
    may not be exposed on all Moodle instances (e.g. behind the WS-only API).
    """
    logger.debug("processing_course", course=course_name, course_id=course_id)

    refs: list[BookReference] = []

    # Primary: always available via AJAX API
    sections = await courses.get_course_content(course_id)
    refs.extend(_extract_from_sections(sections, extractor, course_id))

    # Best-effort: mod_* functions may not be available via AJAX
    resource_refs = await _try_resource_extraction(course_id, resources, extractor)
    refs.extend(resource_refs)

    enriched = [ref.model_copy(update={"course_name": course_name}) for ref in refs]
    logger.debug("course_refs_found", course=course_name, count=len(enriched))
    return enriched


async def _try_resource_extraction(
    course_id: int,
    resources: ResourceProvider,
    extractor: ReferenceExtractor,
) -> list[BookReference]:
    """Attempt to fetch resources via mod_* API calls (best-effort).

    These web service functions may not be available via the AJAX endpoint
    on all Moodle instances. Failures are logged and silently skipped.
    """
    results = await asyncio.gather(
        resources.get_course_books([course_id]),
        resources.get_course_pages([course_id]),
        resources.get_course_resources([course_id]),
        return_exceptions=True,
    )

    sources = [ReferenceSource.RESOURCE_NAME, ReferenceSource.PAGE, ReferenceSource.RESOURCE_NAME]
    refs: list[BookReference] = []

    for result, source in zip(results, sources, strict=True):
        if isinstance(result, BaseException):
            logger.debug(
                "resource_fetch_skipped",
                course_id=course_id,
                source=source,
                error=str(result),
            )
            continue
        refs.extend(_extract_from_modules(result, extractor, course_id, source))

    return refs


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
    return refs


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
