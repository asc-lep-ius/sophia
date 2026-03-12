"""Tests for the async Opencast adapter (TUWEL Moodle Opencast scraper)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from sophia.adapters.lecturetube import OpencastAdapter
from sophia.domain.errors import AuthError, LectureTubeError
from sophia.domain.models import Lecture, LectureTrack
from sophia.domain.ports import LectureProvider

HOST = "https://tuwel.tuwien.ac.at"
MODULE_ID = 2853588
EPISODE_UUID = "d7f06afa-47ae-47bf-bd5f-4c085dc184f9"
EPISODE_UUID_2 = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# ------------------------------------------------------------------
# HTML response fixtures
# ------------------------------------------------------------------

SERIES_PAGE_HTML = (
    "<html><body>"
    '<div class="course-content">'
    "<h2>Algorithms VU 2026S</h2>"
    '<div class="opencast-videos">'
    f'<a href="/mod/opencast/view.php?id={MODULE_ID}&amp;e={EPISODE_UUID}">'
    '<img alt="Lecture 1: Introduction" />'
    "<span>Lecture 1: Introduction</span>"
    "</a>"
    f'<a href="/mod/opencast/view.php?id={MODULE_ID}&amp;e={EPISODE_UUID_2}">'
    "<span>Lecture 2: Sorting</span>"
    "</a>"
    "</div>"
    "</div>"
    "</body></html>"
)

SERIES_PAGE_EMPTY_HTML = (
    '<html><body><div class="course-content"><h2>Empty Course</h2></div></body></html>'
)

EPISODE_PAGE_HTML = (
    "<html><head></head><body>"
    "<script>"
    'window.episode = {"metadata":{"id":"d7f06afa-47ae-47bf-bd5f-4c085dc184f9",'
    '"title":"Lecture 1: Introduction","duration":5400,"series":"s-001",'
    '"seriestitle":"Algorithms VU 2026S","startDate":"2026-03-01T10:00:00Z",'
    '"presenter":"Prof. Smith"},"streams":[{"content":"presenter","sources":'
    '{"mp4":[{"src":"https://cdn.example.com/presenter.mp4","mimetype":"video/mp4",'
    '"res":{"w":1920,"h":1080}}]}}],"frameList":[],"captions":[]};'
    "</script>"
    '<iframe id="opencast-player"></iframe>'
    "</body></html>"
)

EPISODE_PAGE_NO_DATA_HTML = (
    "<html><head></head><body>"
    '<div class="player-container">'
    "<p>No video available.</p>"
    "</div>"
    "</body></html>"
)

EPISODE_PAGE_INVALID_JSON_HTML = (
    "<html><head></head><body><script>window.episode = {invalid json here};</script></body></html>"
)

LOGIN_REDIRECT_URL = "https://tuwel.tuwien.ac.at/login/index.php"


# ------------------------------------------------------------------
# Structural conformance helper
# ------------------------------------------------------------------


def _conforms_to(instance: object, protocol: type) -> bool:
    """Check structural conformance without requiring @runtime_checkable."""
    hints = {
        name
        for name in dir(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }
    return all(callable(getattr(instance, name, None)) for name in hints)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=HOST,
        cookies={"MoodleSession": "test-session-abc"},
    )


@pytest.fixture
def adapter(client: httpx.AsyncClient) -> OpencastAdapter:
    return OpencastAdapter(http=client, host=HOST)


# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------


class TestProtocolConformance:
    def test_conforms_to_lecture_provider(self, adapter: OpencastAdapter) -> None:
        assert _conforms_to(adapter, LectureProvider)


# ------------------------------------------------------------------
# get_series_episodes
# ------------------------------------------------------------------


class TestGetSeriesEpisodes:
    @respx.mock
    async def test_success_multiple_episodes(self, adapter: OpencastAdapter) -> None:
        respx.get(f"{HOST}/mod/opencast/view.php").mock(
            return_value=httpx.Response(200, html=SERIES_PAGE_HTML),
        )

        episodes = await adapter.get_series_episodes(MODULE_ID)

        assert len(episodes) == 2
        assert all(isinstance(e, Lecture) for e in episodes)
        assert episodes[0].episode_id == EPISODE_UUID
        assert episodes[0].title == "Lecture 1: Introduction"
        assert episodes[0].series_title == "Algorithms VU 2026S"
        assert episodes[1].episode_id == EPISODE_UUID_2
        assert episodes[1].title == "Lecture 2: Sorting"

    @respx.mock
    async def test_empty_no_episode_links(self, adapter: OpencastAdapter) -> None:
        respx.get(f"{HOST}/mod/opencast/view.php").mock(
            return_value=httpx.Response(200, html=SERIES_PAGE_EMPTY_HTML),
        )

        episodes = await adapter.get_series_episodes(MODULE_ID)

        assert episodes == []

    async def test_auth_redirect_raises(self, adapter: OpencastAdapter) -> None:
        mock_resp = httpx.Response(
            200,
            text="<html>Login</html>",
            request=httpx.Request("GET", LOGIN_REDIRECT_URL),
        )
        adapter._http = AsyncMock()  # pyright: ignore[reportPrivateUsage]
        adapter._http.get = AsyncMock(return_value=mock_resp)  # pyright: ignore[reportPrivateUsage]

        with pytest.raises(AuthError, match="log in again"):
            await adapter.get_series_episodes(MODULE_ID)

    @respx.mock
    async def test_http_error_raises(self, adapter: OpencastAdapter) -> None:
        respx.get(f"{HOST}/mod/opencast/view.php").mock(
            return_value=httpx.Response(500),
        )

        with pytest.raises(LectureTubeError, match="HTTP 500"):
            await adapter.get_series_episodes(MODULE_ID)


# ------------------------------------------------------------------
# get_episode_detail
# ------------------------------------------------------------------


class TestGetEpisodeDetail:
    @respx.mock
    async def test_success_with_tracks(self, adapter: OpencastAdapter) -> None:
        respx.get(f"{HOST}/mod/opencast/view.php").mock(
            return_value=httpx.Response(200, html=EPISODE_PAGE_HTML),
        )

        lecture = await adapter.get_episode_detail(MODULE_ID, EPISODE_UUID)

        assert lecture is not None
        assert lecture.episode_id == EPISODE_UUID
        assert lecture.title == "Lecture 1: Introduction"
        assert lecture.series_id == "s-001"
        assert lecture.series_title == "Algorithms VU 2026S"
        assert lecture.duration_ms == 5_400_000
        assert lecture.created == "2026-03-01T10:00:00Z"
        assert lecture.creator == "Prof. Smith"
        assert len(lecture.tracks) == 1
        assert lecture.tracks[0] == LectureTrack(
            flavor="presenter/mp4",
            url="https://cdn.example.com/presenter.mp4",
            mimetype="video/mp4",
            resolution="1920x1080",
        )

    @respx.mock
    async def test_no_episode_data_returns_none(self, adapter: OpencastAdapter) -> None:
        respx.get(f"{HOST}/mod/opencast/view.php").mock(
            return_value=httpx.Response(200, html=EPISODE_PAGE_NO_DATA_HTML),
        )

        result = await adapter.get_episode_detail(MODULE_ID, EPISODE_UUID)

        assert result is None

    @respx.mock
    async def test_invalid_json_returns_none(self, adapter: OpencastAdapter) -> None:
        respx.get(f"{HOST}/mod/opencast/view.php").mock(
            return_value=httpx.Response(200, html=EPISODE_PAGE_INVALID_JSON_HTML),
        )

        result = await adapter.get_episode_detail(MODULE_ID, EPISODE_UUID)

        assert result is None

    async def test_auth_redirect_raises(self, adapter: OpencastAdapter) -> None:
        mock_resp = httpx.Response(
            200,
            text="<html>Login</html>",
            request=httpx.Request("GET", LOGIN_REDIRECT_URL),
        )
        adapter._http = AsyncMock()  # pyright: ignore[reportPrivateUsage]
        adapter._http.get = AsyncMock(return_value=mock_resp)  # pyright: ignore[reportPrivateUsage]

        with pytest.raises(AuthError, match="log in again"):
            await adapter.get_episode_detail(MODULE_ID, EPISODE_UUID)

    @respx.mock
    async def test_http_error_raises(self, adapter: OpencastAdapter) -> None:
        respx.get(f"{HOST}/mod/opencast/view.php").mock(
            return_value=httpx.Response(403),
        )

        with pytest.raises(LectureTubeError, match="HTTP 403"):
            await adapter.get_episode_detail(MODULE_ID, EPISODE_UUID)
