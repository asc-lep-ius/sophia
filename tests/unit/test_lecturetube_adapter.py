"""Tests for the async LectureTube adapter (Opencast Search API client)."""

from __future__ import annotations

import httpx
import pytest
import respx

from sophia.adapters.lecturetube import LectureTubeAdapter
from sophia.domain.errors import AuthError, LectureTubeError
from sophia.domain.models import Lecture, LectureSeries, LectureTrack
from sophia.domain.ports import LectureProvider

HOST = "https://lecturetube.tuwien.ac.at"

# ------------------------------------------------------------------
# JSON response fixtures
# ------------------------------------------------------------------

SERIES_SEARCH_RESPONSE = {
    "search-results": {
        "total": "2",
        "offset": "0",
        "limit": "20",
        "result": [
            {
                "id": "s-001",
                "mediapackage": {"id": "s-001", "title": "Algorithms VU 2026S"},
                "dcTitle": "Algorithms VU 2026S",
            },
            {
                "id": "s-002",
                "mediapackage": {"id": "s-002", "title": "Operating Systems VU 2026S"},
                "dcTitle": "Operating Systems VU 2026S",
            },
        ],
    }
}

SERIES_SINGLE_RESULT_RESPONSE = {
    "search-results": {
        "total": "1",
        "offset": "0",
        "limit": "20",
        "result": {
            "id": "s-001",
            "mediapackage": {"id": "s-001", "title": "Algorithms VU 2026S"},
            "dcTitle": "Algorithms VU 2026S",
        },
    }
}

SERIES_EMPTY_RESPONSE = {
    "search-results": {
        "total": "0",
        "offset": "0",
        "limit": "20",
    }
}

EPISODE_RESPONSE = {
    "search-results": {
        "total": "2",
        "offset": "0",
        "limit": "100",
        "result": [
            {
                "id": "ep-001",
                "mediapackage": {
                    "id": "ep-001",
                    "title": "Lecture 1: Introduction",
                    "series": "s-001",
                    "seriestitle": "Algorithms VU 2026S",
                    "duration": "5400000",
                    "start": "2026-03-01T10:00:00Z",
                    "creators": {"creator": "Prof. Smith"},
                    "media": {
                        "track": [
                            {
                                "type": "presenter/delivery",
                                "url": "https://cdn.example.com/ep001-presenter.mp4",
                                "mimetype": "video/mp4",
                                "video": {"resolution": "1920x1080"},
                            },
                            {
                                "type": "presentation/delivery",
                                "url": "https://cdn.example.com/ep001-slides.mp4",
                                "mimetype": "video/mp4",
                                "video": {"resolution": "1280x720"},
                            },
                        ]
                    },
                },
            },
            {
                "id": "ep-002",
                "mediapackage": {
                    "id": "ep-002",
                    "title": "Lecture 2: Sorting",
                    "series": "s-001",
                    "seriestitle": "Algorithms VU 2026S",
                    "duration": "3600000",
                    "start": "2026-03-08T10:00:00Z",
                    "creators": {"creator": "Prof. Smith"},
                    "media": {
                        "track": {
                            "type": "presenter/delivery",
                            "url": "https://cdn.example.com/ep002-presenter.mp4",
                            "mimetype": "video/mp4",
                            "video": {"resolution": "1920x1080"},
                        }
                    },
                },
            },
        ],
    }
}

EPISODE_SINGLE_RESULT_RESPONSE = {
    "search-results": {
        "total": "1",
        "offset": "0",
        "limit": "100",
        "result": {
            "id": "ep-001",
            "mediapackage": {
                "id": "ep-001",
                "title": "Lecture 1: Introduction",
                "series": "s-001",
                "seriestitle": "Algorithms VU 2026S",
                "duration": "5400000",
                "start": "2026-03-01T10:00:00Z",
                "creators": {"creator": "Prof. Smith"},
                "media": {
                    "track": {
                        "type": "presenter/delivery",
                        "url": "https://cdn.example.com/ep001-presenter.mp4",
                        "mimetype": "video/mp4",
                        "video": {"resolution": "1920x1080"},
                    }
                },
            },
        },
    }
}

EPISODE_EMPTY_RESPONSE = {
    "search-results": {
        "total": "0",
        "offset": "0",
        "limit": "100",
    }
}

EPISODE_MISSING_FIELDS_RESPONSE = {
    "search-results": {
        "total": "1",
        "offset": "0",
        "limit": "100",
        "result": {
            "id": "ep-003",
            "mediapackage": {
                "id": "ep-003",
                "title": "Minimal Lecture",
                "series": "s-001",
                "media": {
                    "track": {
                        "type": "presenter/delivery",
                        "url": "https://cdn.example.com/ep003.mp4",
                        "mimetype": "video/mp4",
                    }
                },
            },
        },
    }
}


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
    return httpx.AsyncClient(base_url=HOST)


@pytest.fixture
def adapter(client: httpx.AsyncClient) -> LectureTubeAdapter:
    return LectureTubeAdapter(http=client, host=HOST)


# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------


class TestProtocolConformance:
    def test_conforms_to_lecture_provider(self, adapter: LectureTubeAdapter) -> None:
        assert _conforms_to(adapter, LectureProvider)


# ------------------------------------------------------------------
# search_series
# ------------------------------------------------------------------


class TestSearchSeries:
    @respx.mock
    async def test_success_multiple_results(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/series.json").mock(
            return_value=httpx.Response(200, json=SERIES_SEARCH_RESPONSE),
        )

        results = await adapter.search_series("Algorithms")

        assert len(results) == 2
        assert all(isinstance(r, LectureSeries) for r in results)
        assert results[0].series_id == "s-001"
        assert results[0].title == "Algorithms VU 2026S"
        assert results[1].series_id == "s-002"
        assert results[1].title == "Operating Systems VU 2026S"

    @respx.mock
    async def test_empty_results(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/series.json").mock(
            return_value=httpx.Response(200, json=SERIES_EMPTY_RESPONSE),
        )

        results = await adapter.search_series("NonexistentCourse")

        assert results == []

    @respx.mock
    async def test_single_result_not_array(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/series.json").mock(
            return_value=httpx.Response(200, json=SERIES_SINGLE_RESULT_RESPONSE),
        )

        results = await adapter.search_series("Algorithms")

        assert len(results) == 1
        assert results[0].series_id == "s-001"
        assert results[0].title == "Algorithms VU 2026S"

    @respx.mock
    async def test_http_error_raises(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/series.json").mock(
            return_value=httpx.Response(500),
        )

        with pytest.raises(LectureTubeError, match="HTTP 500"):
            await adapter.search_series("Algorithms")


# ------------------------------------------------------------------
# get_episodes
# ------------------------------------------------------------------


class TestGetEpisodes:
    @respx.mock
    async def test_success_with_multiple_tracks(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/episode.json").mock(
            return_value=httpx.Response(200, json=EPISODE_RESPONSE),
        )

        results = await adapter.get_episodes("s-001")

        assert len(results) == 2
        assert all(isinstance(r, Lecture) for r in results)

        first = results[0]
        assert first.episode_id == "ep-001"
        assert first.title == "Lecture 1: Introduction"
        assert first.series_id == "s-001"
        assert first.series_title == "Algorithms VU 2026S"
        assert first.duration_ms == 5400000
        assert first.created == "2026-03-01T10:00:00Z"
        assert first.creator == "Prof. Smith"
        assert len(first.tracks) == 2
        assert first.tracks[0] == LectureTrack(
            flavor="presenter/delivery",
            url="https://cdn.example.com/ep001-presenter.mp4",
            mimetype="video/mp4",
            resolution="1920x1080",
        )
        assert first.tracks[1].flavor == "presentation/delivery"
        assert first.tracks[1].resolution == "1280x720"

    @respx.mock
    async def test_single_track_not_array(self, adapter: LectureTubeAdapter) -> None:
        """Second episode in EPISODE_RESPONSE has a single track (not array)."""
        respx.get(f"{HOST}/search/episode.json").mock(
            return_value=httpx.Response(200, json=EPISODE_RESPONSE),
        )

        results = await adapter.get_episodes("s-001")

        second = results[1]
        assert second.episode_id == "ep-002"
        assert len(second.tracks) == 1
        assert second.tracks[0].flavor == "presenter/delivery"

    @respx.mock
    async def test_empty_results(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/episode.json").mock(
            return_value=httpx.Response(200, json=EPISODE_EMPTY_RESPONSE),
        )

        results = await adapter.get_episodes("s-001")

        assert results == []

    @respx.mock
    async def test_single_result_not_array(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/episode.json").mock(
            return_value=httpx.Response(200, json=EPISODE_SINGLE_RESULT_RESPONSE),
        )

        results = await adapter.get_episodes("s-001")

        assert len(results) == 1
        assert results[0].episode_id == "ep-001"
        assert results[0].title == "Lecture 1: Introduction"

    @respx.mock
    async def test_auth_redirect_raises(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/episode.json").mock(
            return_value=httpx.Response(
                302,
                headers={"location": "https://idp.zid.tuwien.ac.at/simplesaml/login"},
            ),
        )

        with pytest.raises(AuthError, match="log in again"):
            await adapter.get_episodes("s-001")

    @respx.mock
    async def test_http_error_raises(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/episode.json").mock(
            return_value=httpx.Response(500),
        )

        with pytest.raises(LectureTubeError, match="HTTP 500"):
            await adapter.get_episodes("s-001")

    @respx.mock
    async def test_missing_optional_fields(self, adapter: LectureTubeAdapter) -> None:
        respx.get(f"{HOST}/search/episode.json").mock(
            return_value=httpx.Response(200, json=EPISODE_MISSING_FIELDS_RESPONSE),
        )

        results = await adapter.get_episodes("s-001")

        assert len(results) == 1
        ep = results[0]
        assert ep.episode_id == "ep-003"
        assert ep.title == "Minimal Lecture"
        assert ep.duration_ms == 0
        assert ep.created == ""
        assert ep.creator == ""
        assert ep.series_title == ""
        assert len(ep.tracks) == 1
        assert ep.tracks[0].resolution == ""
