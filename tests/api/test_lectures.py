"""Lectures API route tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sophia.api.routers import lectures as lectures_router
from sophia.services.hermes_catalog import DiscoveredLectureModule, LectureModule
from sophia.services.hermes_manage import EpisodeStatus

from ._session_helpers import build_harness, csrf_headers, login

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: object


def test_lecture_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    modules_response = harness.client.get("/api/lectures/modules")
    episodes_response = harness.client.get("/api/lectures/modules/12/episodes")
    status_response = harness.client.get("/api/lectures/modules/12/pipeline-status")
    discover_response = harness.client.post(
        "/api/lectures/discover",
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert modules_response.status_code == 401
    assert episodes_response.status_code == 401
    assert status_response.status_code == 401
    assert discover_response.status_code == 401


def test_list_lecture_modules_returns_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(app_container=cast("AppContainer", fake_app))
    login(harness)

    async def fake_get_lecture_modules(db: object) -> list[LectureModule]:
        assert db is fake_app.db
        return [
            LectureModule(module_id=12, series_id="series-12", course_name="Algorithms"),
        ]

    monkeypatch.setattr(lectures_router, "get_lecture_modules", fake_get_lecture_modules)

    response = harness.client.get("/api/lectures/modules")

    assert response.status_code == 200
    assert response.json() == {
        "modules": [
            {"module_id": 12, "series_id": "series-12", "course_name": "Algorithms"},
        ],
    }


def test_list_module_episodes_returns_status_rows(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr(lectures_router, "get_pipeline_status", fake_get_pipeline_status)

    response = harness.client.get("/api/lectures/modules/12/episodes")

    assert response.status_code == 200
    assert response.json() == {
        "module_id": 12,
        "episodes": [
            {
                "episode_id": "episode-1",
                "title": "Lecture 1",
                "download_status": "completed",
                "skip_reason": None,
                "transcription_status": "completed",
                "index_status": "completed",
                "lecture_number": 1,
                "missed_at": None,
            },
        ],
    }


def test_module_episodes_return_404_when_module_has_no_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    async def fake_get_pipeline_status(_db: object, _module_id: int) -> list[EpisodeStatus]:
        return []

    monkeypatch.setattr(lectures_router, "get_pipeline_status", fake_get_pipeline_status)

    response = harness.client.get("/api/lectures/modules/999/episodes")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_lecture_path_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.get("/api/lectures/modules/0/episodes")

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}


def test_discover_lecture_modules_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post("/api/lectures/discover")

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_discover_lecture_modules_returns_discovered_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(app_container=cast("AppContainer", fake_app))
    login(harness)

    async def fake_discover_lecture_modules(app: AppContainer) -> list[DiscoveredLectureModule]:
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
        lectures_router,
        "discover_lecture_modules",
        fake_discover_lecture_modules,
    )

    response = harness.client.post("/api/lectures/discover", headers=csrf_headers(harness))

    assert response.status_code == 200
    assert response.json() == {
        "modules": [
            {
                "course_shortname": "algo",
                "course_fullname": "Algorithms",
                "module_id": 12,
                "module_name": "Lecture recordings",
                "episode_count": 2,
            },
        ],
    }


def test_lecture_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    openapi = harness.app.openapi()

    assert openapi["paths"]["/api/lectures/modules"]["get"]["tags"] == ["lectures"]
    assert openapi["paths"]["/api/lectures/modules"]["get"]["operationId"] == "listLectureModules"
    assert (
        openapi["paths"]["/api/lectures/modules/{module_id}/episodes"]["get"]["operationId"]
        == "listLectureModuleEpisodes"
    )
    assert (
        openapi["paths"]["/api/lectures/modules/{module_id}/pipeline-status"]["get"]["operationId"]
        == "readLecturePipelineStatus"
    )
    assert (
        openapi["paths"]["/api/lectures/discover"]["post"]["operationId"]
        == "discoverLectureModules"
    )
