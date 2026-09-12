"""Content source and content item API route tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from sophia.api.routers import content_sources as content_sources_router
from sophia.services.content_uploads import staging_dir
from sophia.services.hermes_catalog import DiscoveredLectureModule, LectureModule
from sophia.services.hermes_manage import EpisodeStatus

from ._session_helpers import ApiHarness, FakeAppContainer, build_harness, csrf_headers, login

# The learning path `_session_helpers.login` puts on the session. Uploads are
# staged under it, so the tests have to look in the same place the handler did.
SESSION_LEARNING_PATH_ID = "course-1"

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import Response

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


def _upload_harness(tmp_path: Path) -> ApiHarness:
    """A logged-in harness whose uploads land in a throwaway directory."""
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    harness.settings.data_dir = tmp_path
    login(harness)
    return harness


def test_upload_accepts_a_multipart_post_and_reports_it_queued(tmp_path: Path) -> None:
    harness = _upload_harness(tmp_path)

    response = harness.client.post(
        "/api/content-sources/uploads",
        data={"title": "  Graph algorithms  "},
        files={"file": ("lecture-01.pdf", b"%PDF-1.7\ntrailer", "application/pdf")},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Graph algorithms"
    assert body["media_type"] == "application/pdf"
    assert body["byte_size"] == len(b"%PDF-1.7\ntrailer")
    assert body["state"] == "queued"
    staged = staging_dir(tmp_path, SESSION_LEARNING_PATH_ID) / f"{body['id']}.pdf"
    # Scoped to the session's own learning path, not dropped in a shared bucket.
    assert staged.exists()


@pytest.mark.parametrize(
    ("title", "upload_file", "reason"),
    [
        ("   ", ("lecture-01.pdf", b"%PDF-1.7\n", "application/pdf"), "title_required"),
        ("Payload", ("payload.exe", b"MZ\x90\x00", "application/pdf"), "unsupported_type"),
        ("Disguised", ("lecture-01.pdf", b"MZ\x90\x00", "application/pdf"), "content_mismatch"),
        ("Nothing", ("lecture-01.pdf", b"", "application/pdf"), "empty_file"),
    ],
)
def test_upload_returns_a_named_validation_error(
    tmp_path: Path,
    title: str,
    upload_file: tuple[str, bytes, str],
    reason: str,
) -> None:
    """A refused upload says which check refused it.

    The declared part content-type is `application/pdf` in every case on
    purpose: a caller controls that header, so it must never be what decides.
    """
    harness = _upload_harness(tmp_path)

    response = harness.client.post(
        "/api/content-sources/uploads",
        data={"title": title},
        files={"file": upload_file},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "content.upload_rejected"
    assert response.json()["detail"]["params"]["reason"] == reason


def test_upload_refuses_a_payload_over_the_configured_ceiling(tmp_path: Path) -> None:
    harness = _upload_harness(tmp_path)
    harness.settings.content_upload_max_bytes = 16

    response = harness.client.post(
        "/api/content-sources/uploads",
        data={"title": "Too big"},
        files={"file": ("lecture-01.pdf", b"%PDF-1.7\n" + b"0" * 4096, "application/pdf")},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["params"] == {"reason": "too_large", "max_bytes": 16}
    assert list(staging_dir(tmp_path, SESSION_LEARNING_PATH_ID).iterdir()) == []


def test_upload_requires_authentication_and_csrf(tmp_path: Path) -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    harness.settings.data_dir = tmp_path

    def post_upload() -> Response:
        return harness.client.post(
            "/api/content-sources/uploads",
            data={"title": "Graph algorithms"},
            files={"file": ("lecture-01.pdf", b"%PDF-1.7\n", "application/pdf")},
        )

    anonymous_response = post_upload()
    login(harness)
    no_csrf_response = post_upload()

    assert anonymous_response.status_code == 401
    assert no_csrf_response.status_code == 403
    # Neither refusal may have written anything: the checks run before the
    # staging directory is created, not after.
    assert not staging_dir(tmp_path, SESSION_LEARNING_PATH_ID).exists()


def test_upload_body_is_a_named_multipart_component() -> None:
    """The generated client needs a stable name, not FastAPI's `Body_...`."""
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    operation = harness.app.openapi()["paths"]["/api/content-sources/uploads"]["post"]

    assert operation["operationId"] == "createContentSourceUpload"
    assert operation["requestBody"]["content"]["multipart/form-data"]["schema"] == {
        "$ref": "#/components/schemas/ContentSourceUploadForm",
    }
