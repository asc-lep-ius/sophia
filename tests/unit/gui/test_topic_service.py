"""Tests for GUI topic service wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from sophia.domain.models import ConfidenceRating, TopicMapping, TopicSource

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

COURSE_ID = 42
MODULE_ID = 42

_PATCH_BASE = "sophia.gui.services.topic_service"
_EXPORT_CORE = "sophia.services.athena_export.export_anki_deck"


def _make_topic(**overrides: str | int) -> TopicMapping:
    defaults: dict[str, str | int] = {
        "topic": "Sorting algorithms",
        "course_id": COURSE_ID,
        "source": TopicSource.LECTURE,
        "frequency": 3,
    }
    defaults.update(overrides)
    return TopicMapping(**defaults)  # type: ignore[arg-type]


def _make_rating(**overrides: str | int | float | None) -> ConfidenceRating:
    defaults: dict[str, str | int | float | None] = {
        "topic": "Sorting algorithms",
        "course_id": COURSE_ID,
        "predicted": 0.75,
        "actual": 0.5,
        "rated_at": "2026-03-28T12:00:00",
    }
    defaults.update(overrides)
    return ConfidenceRating(**defaults)  # type: ignore[arg-type]


# -- get_course_topics -------------------------------------------------------


class TestGetCourseTopics:
    @pytest.mark.asyncio
    async def test_returns_topics(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import get_course_topics

        expected = [_make_topic(), _make_topic(topic="Graph theory")]
        with patch(
            f"{_PATCH_BASE}._get_course_topics",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fn:
            result = await get_course_topics(mock_container, course_id=COURSE_ID)

        assert result == expected
        mock_fn.assert_awaited_once_with(mock_container, COURSE_ID)

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import get_course_topics

        with patch(
            f"{_PATCH_BASE}._get_course_topics",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db timeout"),
        ):
            result = await get_course_topics(mock_container, course_id=COURSE_ID)

        assert result == []


# -- extract_topics ----------------------------------------------------------


class TestExtractTopics:
    @pytest.mark.asyncio
    async def test_delegates_to_core(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import extract_topics

        expected = [_make_topic()]
        with patch(
            f"{_PATCH_BASE}._extract_topics",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fn:
            result = await extract_topics(mock_container, module_id=MODULE_ID)

        assert result == expected
        mock_fn.assert_awaited_once_with(mock_container, MODULE_ID, on_progress=None, force=False)

    @pytest.mark.asyncio
    async def test_passes_force_param(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import extract_topics

        with patch(
            f"{_PATCH_BASE}._extract_topics",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fn:
            await extract_topics(mock_container, module_id=MODULE_ID, force=True)

        mock_fn.assert_awaited_once_with(mock_container, MODULE_ID, on_progress=None, force=True)

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import extract_topics

        with patch(
            f"{_PATCH_BASE}._extract_topics",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM timeout"),
        ):
            result = await extract_topics(mock_container, module_id=MODULE_ID)

        assert result == []


# -- get_topic_confidence ----------------------------------------------------


class TestGetTopicConfidence:
    @pytest.mark.asyncio
    async def test_returns_rating(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import get_topic_confidence

        all_ratings = [_make_rating(), _make_rating(topic="Graph theory")]
        with patch(
            f"{_PATCH_BASE}._get_confidence_ratings",
            new_callable=AsyncMock,
            return_value=all_ratings,
        ):
            result = await get_topic_confidence(
                mock_container, course_id=COURSE_ID, topic="Sorting algorithms"
            )

        assert result is not None
        assert result.topic == "Sorting algorithms"

    @pytest.mark.asyncio
    async def test_returns_none_for_unrated(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import get_topic_confidence

        with patch(
            f"{_PATCH_BASE}._get_confidence_ratings",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_topic_confidence(
                mock_container, course_id=COURSE_ID, topic="Unknown topic"
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import get_topic_confidence

        with patch(
            f"{_PATCH_BASE}._get_confidence_ratings",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db error"),
        ):
            result = await get_topic_confidence(
                mock_container, course_id=COURSE_ID, topic="Sorting algorithms"
            )

        assert result is None


# -- save_confidence_prediction ----------------------------------------------


class TestSaveConfidencePrediction:
    @pytest.mark.asyncio
    async def test_delegates_to_core(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import save_confidence_prediction

        expected = _make_rating(actual=None)
        with patch(
            f"{_PATCH_BASE}._rate_confidence",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fn:
            result = await save_confidence_prediction(
                mock_container, topic="Sorting algorithms", course_id=COURSE_ID, rating=4
            )

        assert result == expected
        mock_fn.assert_awaited_once_with(mock_container, "Sorting algorithms", COURSE_ID, 4)

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import save_confidence_prediction

        with patch(
            f"{_PATCH_BASE}._rate_confidence",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db error"),
        ):
            result = await save_confidence_prediction(
                mock_container, topic="Sorting algorithms", course_id=COURSE_ID, rating=4
            )

        assert result is None


# -- export_anki_deck -------------------------------------------------------


class TestExportAnkiDeck:
    @pytest.mark.asyncio
    async def test_returns_bytes_on_success(
        self, mock_container: AppContainer, tmp_path: object
    ) -> None:
        from sophia.gui.services.topic_service import export_anki_deck

        apkg_bytes = b"PK\x03\x04fake-apkg-content"

        async def _fake_export(
            db: object,
            course_id: int,
            output_path: object,
            *,
            episode_id: str | None = None,
            interleaved: bool = True,
        ) -> int:
            from pathlib import Path

            Path(str(output_path)).write_bytes(apkg_bytes)
            return 5

        with patch(_EXPORT_CORE, side_effect=_fake_export):
            result = await export_anki_deck(mock_container, course_id=COURSE_ID)

        assert result == apkg_bytes

    @pytest.mark.asyncio
    async def test_returns_none_when_no_cards(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import export_anki_deck

        async def _fake_export(
            db: object,
            course_id: int,
            output_path: object,
            *,
            episode_id: str | None = None,
            interleaved: bool = True,
        ) -> int:
            return 0

        with patch(_EXPORT_CORE, side_effect=_fake_export):
            result = await export_anki_deck(mock_container, course_id=COURSE_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import export_anki_deck

        with patch(
            _EXPORT_CORE,
            new_callable=AsyncMock,
            side_effect=RuntimeError("genanki exploded"),
        ):
            result = await export_anki_deck(mock_container, course_id=COURSE_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_passes_episode_id(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.topic_service import export_anki_deck

        async def _fake_export(
            db: object,
            course_id: int,
            output_path: object,
            *,
            episode_id: str | None = None,
            interleaved: bool = True,
        ) -> int:
            from pathlib import Path

            assert episode_id == "ep-42"
            assert interleaved is False
            Path(str(output_path)).write_bytes(b"content")
            return 3

        with patch(_EXPORT_CORE, side_effect=_fake_export):
            result = await export_anki_deck(
                mock_container,
                course_id=COURSE_ID,
                episode_id="ep-42",
                interleaved=False,
            )

        assert result is not None
