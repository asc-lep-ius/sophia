"""Tests for the Lectures landing page — setup-complete gate logic & pure helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sophia.gui.pages.lectures import is_hermes_setup_complete
from sophia.gui.services.hermes_service import (
    STATUS_FILTER_ALL,
    STATUS_FILTER_INDEXED,
    STATUS_FILTER_NEEDS_PROCESSING,
    count_unprocessed,
    filter_episodes,
    get_unprocessed,
    is_fully_indexed,
    needs_processing,
)
from sophia.gui.state.storage_map import USER_HERMES_SETUP_COMPLETE
from sophia.services.hermes_manage import EpisodeStatus

# --- Fixtures ----------------------------------------------------------------


def _ep(
    *,
    dl: str = "completed",
    tr: str | None = "completed",
    idx: str | None = "completed",
    title: str = "Lecture 1",
    episode_id: str = "e1",
) -> EpisodeStatus:
    """Shorthand factory for EpisodeStatus."""
    return EpisodeStatus(
        episode_id=episode_id,
        title=title,
        download_status=dl,
        skip_reason=None,
        transcription_status=tr,
        index_status=idx,
    )


# --- Existing tests ----------------------------------------------------------


class TestIsHermesSetupComplete:
    """Verify the boolean gate that controls setup-vs-dashboard rendering."""

    def test_returns_false_when_key_missing(self) -> None:
        mock_app = MagicMock()
        mock_app.storage.user = {}
        with patch("sophia.gui.pages.lectures.app", mock_app):
            assert is_hermes_setup_complete() is False

    def test_returns_false_when_key_is_false(self) -> None:
        mock_app = MagicMock()
        mock_app.storage.user = {USER_HERMES_SETUP_COMPLETE: False}
        with patch("sophia.gui.pages.lectures.app", mock_app):
            assert is_hermes_setup_complete() is False

    def test_returns_true_when_key_is_true(self) -> None:
        mock_app = MagicMock()
        mock_app.storage.user = {USER_HERMES_SETUP_COMPLETE: True}
        with patch("sophia.gui.pages.lectures.app", mock_app):
            assert is_hermes_setup_complete() is True


# --- Pure helper tests -------------------------------------------------------


class TestIsFullyIndexed:
    """All three pipeline stages must be 'completed'."""

    def test_all_completed(self) -> None:
        assert is_fully_indexed(_ep()) is True

    @pytest.mark.parametrize(
        ("dl", "tr", "idx"),
        [
            ("queued", "completed", "completed"),
            ("completed", None, "completed"),
            ("completed", "completed", None),
            ("completed", "completed", "queued"),
            ("failed", "completed", "completed"),
            ("completed", "failed", None),
            ("skipped", None, None),
        ],
    )
    def test_not_fully_indexed(self, dl: str, tr: str | None, idx: str | None) -> None:
        assert is_fully_indexed(_ep(dl=dl, tr=tr, idx=idx)) is False


class TestNeedsProcessing:
    """Inverse of is_fully_indexed."""

    def test_fully_indexed_does_not_need_processing(self) -> None:
        assert needs_processing(_ep()) is False

    def test_partial_needs_processing(self) -> None:
        assert needs_processing(_ep(idx=None)) is True

    def test_failed_needs_processing(self) -> None:
        assert needs_processing(_ep(dl="failed")) is True


class TestFilterEpisodes:
    """Status filter and text search."""

    @pytest.fixture
    def episodes(self) -> list[EpisodeStatus]:
        return [
            _ep(title="Intro to ML", episode_id="e1"),
            _ep(title="Deep Learning", episode_id="e2", idx=None),
            _ep(title="Reinforcement Learning", episode_id="e3", tr=None, idx=None),
        ]

    def test_filter_all(self, episodes: list[EpisodeStatus]) -> None:
        result = filter_episodes(episodes, status_filter=STATUS_FILTER_ALL, search_query="")
        assert len(result) == 3

    def test_filter_indexed(self, episodes: list[EpisodeStatus]) -> None:
        result = filter_episodes(episodes, status_filter=STATUS_FILTER_INDEXED, search_query="")
        assert len(result) == 1
        assert result[0].episode_id == "e1"

    def test_filter_needs_processing(self, episodes: list[EpisodeStatus]) -> None:
        result = filter_episodes(
            episodes,
            status_filter=STATUS_FILTER_NEEDS_PROCESSING,
            search_query="",
        )
        assert len(result) == 2

    def test_search_by_title(self, episodes: list[EpisodeStatus]) -> None:
        result = filter_episodes(episodes, status_filter=STATUS_FILTER_ALL, search_query="deep")
        assert len(result) == 1
        assert result[0].title == "Deep Learning"

    def test_search_case_insensitive(self, episodes: list[EpisodeStatus]) -> None:
        result = filter_episodes(episodes, status_filter=STATUS_FILTER_ALL, search_query="INTRO")
        assert len(result) == 1

    def test_combined_filter_and_search(self, episodes: list[EpisodeStatus]) -> None:
        result = filter_episodes(
            episodes,
            status_filter=STATUS_FILTER_NEEDS_PROCESSING,
            search_query="reinforcement",
        )
        assert len(result) == 1
        assert result[0].episode_id == "e3"

    def test_empty_list(self) -> None:
        result = filter_episodes([], status_filter=STATUS_FILTER_ALL, search_query="x")
        assert result == []


# --- count_unprocessed / get_unprocessed -------------------------------------


class TestCountUnprocessed:
    """Count episodes that still need pipeline work."""

    def test_all_indexed(self) -> None:
        eps = [_ep(episode_id="e1"), _ep(episode_id="e2")]
        assert count_unprocessed(eps) == 0

    def test_some_unprocessed(self) -> None:
        eps = [_ep(episode_id="e1"), _ep(episode_id="e2", idx=None)]
        assert count_unprocessed(eps) == 1

    def test_all_unprocessed(self) -> None:
        eps = [_ep(dl="queued", tr=None, idx=None), _ep(idx=None)]
        assert count_unprocessed(eps) == 2

    def test_empty_list(self) -> None:
        assert count_unprocessed([]) == 0


class TestGetUnprocessed:
    """Filter to only unprocessed episodes."""

    def test_returns_only_unprocessed(self) -> None:
        eps = [
            _ep(episode_id="e1"),
            _ep(episode_id="e2", idx=None),
            _ep(episode_id="e3", tr=None, idx=None),
        ]
        result = get_unprocessed(eps)
        assert len(result) == 2
        assert {ep.episode_id for ep in result} == {"e2", "e3"}

    def test_empty_when_all_indexed(self) -> None:
        eps = [_ep(episode_id="e1"), _ep(episode_id="e2")]
        assert get_unprocessed(eps) == []

    def test_empty_list(self) -> None:
        assert get_unprocessed([]) == []
