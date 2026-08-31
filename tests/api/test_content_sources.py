"""Content source and content item API route tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sophia.api.routers import content_sources as content_sources_router
from sophia.services.hermes_catalog import DiscoveredLectureModule, LectureModule
from sophia.services.hermes_manage import EpisodeStatus

from ._session_helpers import FakeAppContainer, build_harness, csrf_headers, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


def test_content_source_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    sources_response = harness.client.get("/api/content-sources")
    items_response = harness.client.get("/api/content-sources/12/content-items")
    status_response = harness.client.get("/api/content-sources/12/ingestion-status")
    discover_response = harness.client.post(
        "/api/content-sources/discover",
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert sources_response.status_code == 401
    assert items_response.status_code == 401
    assert status_response.status_code == 401
    assert discover_response.status_code == 401


def test_list_content_sources_returns_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(app_container=cast("AppContainer", fake_app))
    login(harness)

    async def fake_get_lecture_modules(db: object) -> list[LectureModule]:
        assert db is fake_app.db
        return [
            LectureModule(module_id=12, series_id="series-12", course_name="Algorithms"),
        ]

    monkeypatch.setattr(content_sources_router, "get_lecture_modules", fake_get_lecture_modules)

    response = harness.client.get("/api/content-sources")

    assert response.status_code == 200
    assert response.json() == {
        "sources": [
            {"id": 12, "external_ref": "series-12", "title": "Algorithms"},
        ],
    }


def test_list_content_items_returns_status_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(app_container=cast("AppContainer", fake_app))
    login(harness)

    async def fake_get_pipeline_status(db: object, module_id: int) -> list[EpisodeStatus]:
        assert db is fake_app.db
        assert module_id == 12
        return [
            EpisodeStatus(
                episode_id="episode-1",
                title="Lecture 1",
                download_status="completed",
                skip_reason=None,
                transcription_status="completed",
                index_status="completed",
                lecture_number=1,
                missed_at=None,
            ),
        ]

    monkeypatch.setattr(content_sources_router, "get_pipeline_status", fake_get_pipeline_status)

    response = harness.client.get("/api/content-sources/12/content-items")

    assert response.status_code == 200
    assert response.json() == {
        "content_source_id": 12,
        "items": [
            {
                "id": "episode-1",
                "title": "Lecture 1",
                "download_status": "completed",
                "skip_reason": None,
                "transcription_status": "completed",
                "index_status": "completed",
                "sequence_number": 1,
                "missed_at": None,
            },
        ],
    }


def test_content_items_return_404_when_source_has_no_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    async def fake_get_pipeline_status(_db: object, _module_id: int) -> list[EpisodeStatus]:
        return []

    monkeypatch.setattr(content_sources_router, "get_pipeline_status", fake_get_pipeline_status)

    response = harness.client.get("/api/content-sources/999/content-items")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_content_source_path_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.get("/api/content-sources/0/content-items")

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}


def test_discover_content_sources_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post("/api/content-sources/discover")

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_discover_content_sources_returns_discovered_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(app_container=cast("AppContainer", fake_app))
    login(harness)

    async def fake_discover_lecture_modules(
        app: AppContainer, db: object
    ) -> list[DiscoveredLectureModule]:
        assert app is fake_app
        return [
            DiscoveredLectureModule(
                course_shortname="algo",
                course_fullname="Algorithms",
                module_id=12,
                module_name="Lecture recordings",
                episode_count=2,
            ),
        ]

    monkeypatch.setattr(
        content_sources_router,
        "discover_lecture_modules",
        fake_discover_lecture_modules,
    )

    response = harness.client.post("/api/content-sources/discover", headers=csrf_headers(harness))

    assert response.status_code == 200
    assert response.json() == {
        "sources": [
            {
                "id": 12,
                "title": "Lecture recordings",
                "learning_path_title": "Algorithms",
                "learning_path_short_title": "algo",
                "content_item_count": 2,
            },
        ],
    }


def test_content_source_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/content-sources"]["get"]["tags"] == ["content-sources"]
    assert openapi["paths"]["/api/content-sources"]["get"]["operationId"] == "listContentSources"
    assert (
        openapi["paths"]["/api/content-sources/{content_source_id}/content-items"]["get"][
            "operationId"
        ]
        == "listContentItems"
    )
    assert (
        openapi["paths"]["/api/content-sources/{content_source_id}/ingestion-status"]["get"][
            "operationId"
        ]
        == "readContentSourceIngestionStatus"
    )
    assert (
        openapi["paths"]["/api/content-sources/discover"]["post"]["operationId"]
        == "discoverContentSources"
    )
