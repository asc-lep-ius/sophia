"""GUI-safe wrappers for Hermes search functionality."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from sophia.domain.errors import SophiaError
from sophia.services.hermes_index import search_lectures as _search_lectures

if TYPE_CHECKING:
    from sophia.domain.models import LectureSearchResult
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


async def search_lectures(
    app: AppContainer,
    module_id: int,
    query: str,
    *,
    n_results: int = 5,
    course_id: int | None = None,
) -> list[LectureSearchResult]:
    """Search lecture transcripts via Hermes index."""
    try:
        return await _search_lectures(
            app, module_id, query, n_results=n_results, course_id=course_id
        )
    except SophiaError:
        raise
    except Exception:
        log.exception("search_lectures_failed", module_id=module_id, query=query)
        return []
