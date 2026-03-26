"""Tests for GUI search service wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from sophia.domain.models import LectureSearchResult

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

MODULE_ID = 7
COURSE_ID = 42
QUERY = "binary search"

_PATCH_BASE = "sophia.gui.services.search_service"


def _make_result(**overrides: Any) -> LectureSearchResult:
    defaults = {
        "episode_id": "ep-1",
        "title": "Lecture 1",
        "chunk_text": "Binary search is...",
        "start_time": 0.0,
        "end_time": 60.0,
        "score": 0.95,
    }
    defaults.update(overrides)
    return LectureSearchResult(**defaults)  # type: ignore[arg-type]


class TestSearchLectures:
    """Tests for search_lectures wrapper."""

    @pytest.mark.asyncio
    async def test_returns_results(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.search_service import search_lectures

        expected = [_make_result(), _make_result(episode_id="ep-2", title="Lecture 2")]
        with patch(
            f"{_PATCH_BASE}._search_lectures",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fn:
            result = await search_lectures(mock_container, MODULE_ID, QUERY)

        assert result == expected
        mock_fn.assert_awaited_once_with(
            mock_container, MODULE_ID, QUERY, n_results=5, course_id=None
        )

    @pytest.mark.asyncio
    async def test_passes_optional_params(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.search_service import search_lectures

        with patch(
            f"{_PATCH_BASE}._search_lectures",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fn:
            await search_lectures(
                mock_container, MODULE_ID, QUERY, n_results=10, course_id=COURSE_ID
            )

        mock_fn.assert_awaited_once_with(
            mock_container, MODULE_ID, QUERY, n_results=10, course_id=COURSE_ID
        )

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.search_service import search_lectures

        with patch(
            f"{_PATCH_BASE}._search_lectures",
            new_callable=AsyncMock,
            side_effect=Exception("connection lost"),
        ):
            result = await search_lectures(mock_container, MODULE_ID, QUERY)

        assert result == []
