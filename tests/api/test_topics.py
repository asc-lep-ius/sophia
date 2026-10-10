"""Topics API route tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import insert

from sophia.api.routers import topics as topics_router
from sophia.api.sessions import SessionTenant
from sophia.domain.models import ConfidenceRating, TopicMapping, TopicSource
from sophia.infra.schema import lecture_modules, transcript_segments, transcriptions

from ._db_harness import db_harness
from ._session_helpers import FakeAppContainer, build_harness, csrf_headers, login

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from sophia.infra.di import AppContainer


def learning_path_tenant(learning_path_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        learning_path_id=str(learning_path_id),
        cohort_id="cohort-a",
        role="student",
    )


def stub_module_owners(monkeypatch: pytest.MonkeyPatch, owners: dict[int, str]) -> None:
    """Pin which learning path owns which content source, without a database."""

    async def fake_owner(_db: object, module_id: int) -> str | None:
        return owners.get(module_id)

    monkeypatch.setattr(topics_router, "get_lecture_module_course_id", fake_owner)


async def _no_origins(_db: object, _course_id: int) -> dict[str, list[object]]:
    return {}


def test_topic_routes_require_authentication() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    topics_response = harness.client.get("/api/learning-paths/12/topics")
    extract_response = harness.client.post(
        "/api/learning-paths/12/topics/extract",
        json={"content_source_id": 12},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )
    confidence_response = harness.client.get("/api/learning-paths/12/topics/confidence")

    assert topics_response.status_code == 401
    assert extract_response.status_code == 401
    assert confidence_response.status_code == 401


def test_list_topics_returns_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_get_course_topics(db: object, course_id: int) -> list[TopicMapping]:
        assert db is fake_app.db
        assert course_id == 12
        return [
            TopicMapping(
                topic="Dynamic programming",
                course_id=12,
                source=TopicSource.LECTURE,
                frequency=3,
            ),
        ]

    monkeypatch.setattr(topics_router, "get_course_topics", fake_get_course_topics)
    monkeypatch.setattr(topics_router, "get_topic_origins", _no_origins)

    response = harness.client.get("/api/learning-paths/12/topics")

    assert response.status_code == 200
    assert response.json() == {
        "learning_path_id": 12,
        "topics": [
            {
                "topic": "Dynamic programming",
                "learning_path_id": 12,
                "source": "transcript",
                "frequency": 3,
                "content_items": [],
            },
        ],
    }


def test_extract_topics_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/learning-paths/12/topics/extract", json={"content_source_id": 12}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_extract_topics_returns_extracted_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)
    stub_module_owners(monkeypatch, {456: "12"})

    async def fake_extract_topics_from_lectures(
        app: AppContainer,
        db: object,
        course_id: int,
        *,
        force: bool = False,
    ) -> list[TopicMapping]:
        assert db is fake_app.db
        assert course_id == 12
        assert force is True
        return [TopicMapping(topic="Graphs", course_id=12, source=TopicSource.LECTURE)]

    monkeypatch.setattr(
        topics_router,
        "extract_topics_from_lectures",
        fake_extract_topics_from_lectures,
    )

    response = harness.client.post(
        "/api/learning-paths/12/topics/extract",
        json={"content_source_id": 456, "force": True},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {
        "content_source_id": 456,
        "topics": [
            {
                "topic": "Graphs",
                "learning_path_id": 12,
                "source": "transcript",
                "frequency": 1,
                "content_items": [],
            },
        ],
    }


def test_save_manual_topic_requires_csrf() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    response = harness.client.post(
        "/api/learning-paths/12/topics",
        json={"topic": "Amortized analysis"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_save_manual_topic_returns_saved_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_save_manual_topic(
        db: object,
        topic: str,
        course_id: int,
    ) -> TopicMapping | None:
        assert db is fake_app.db
        assert topic == "Amortized analysis"
        assert course_id == 12
        return TopicMapping(topic=topic, course_id=course_id, source=TopicSource.MANUAL)

    monkeypatch.setattr(topics_router, "save_manual_topic", fake_save_manual_topic)

    response = harness.client.post(
        "/api/learning-paths/12/topics",
        json={"topic": "Amortized analysis"},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json() == {
        "topic": {
            "topic": "Amortized analysis",
            "learning_path_id": 12,
            "source": "manual",
            "frequency": 1,
            "content_items": [],
        },
    }


def test_confidence_routes_return_response_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_get_confidence_ratings(
        db: object,
        course_id: int,
    ) -> list[ConfidenceRating]:
        assert db is fake_app.db
        assert course_id == 12
        return [
            ConfidenceRating(
                topic="Graphs",
                course_id=12,
                predicted=0.75,
                actual=None,
                rated_at="2026-05-26T12:00:00Z",
            ),
        ]

    async def fake_rate_confidence(
        db: object,
        topic: str,
        course_id: int,
        rating: int,
    ) -> ConfidenceRating:
        assert db is fake_app.db
        assert topic == "Graphs"
        assert course_id == 12
        assert rating == 4
        return ConfidenceRating(
            topic="Graphs",
            course_id=12,
            predicted=0.75,
            actual=None,
            rated_at="2026-05-26T12:00:00Z",
        )

    monkeypatch.setattr(topics_router, "get_confidence_ratings", fake_get_confidence_ratings)
    monkeypatch.setattr(topics_router, "rate_confidence", fake_rate_confidence)

    list_response = harness.client.get("/api/learning-paths/12/topics/confidence")
    save_response = harness.client.post(
        "/api/learning-paths/12/topics/confidence",
        json={"topic": "Graphs", "rating": 4},
        headers=csrf_headers(harness),
    )

    assert list_response.status_code == 200
    assert list_response.json() == {
        "learning_path_id": 12,
        "ratings": [
            {
                "topic": "Graphs",
                "learning_path_id": 12,
                "predicted": 0.75,
                "actual": None,
                "rated_at": "2026-05-26T12:00:00Z",
                "calibration_error": None,
                "is_blind_spot": False,
            },
        ],
    }
    assert save_response.status_code == 200
    assert save_response.json() == {
        "rating": {
            "topic": "Graphs",
            "learning_path_id": 12,
            "predicted": 0.75,
            "actual": None,
            "rated_at": "2026-05-26T12:00:00Z",
            "calibration_error": None,
            "is_blind_spot": False,
        },
    }


def test_topic_confidence_lookup_returns_404_for_missing_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=object())),
        tenant=learning_path_tenant(),
    )
    login(harness)

    async def fake_get_confidence_ratings(
        _db: object,
        _course_id: int,
    ) -> list[ConfidenceRating]:
        return []

    monkeypatch.setattr(topics_router, "get_confidence_ratings", fake_get_confidence_ratings)

    response = harness.client.get("/api/learning-paths/12/topics/confidence?topic=Missing")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "http.not_found", "params": {}}}


def test_topic_routes_reject_out_of_scope_learning_paths_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(12),
    )
    login(harness)
    calls: list[str] = []

    async def fake_get_course_topics(
        _app: AppContainer,
        course_id: int,
    ) -> list[TopicMapping]:
        calls.append(f"topics:{course_id}")
        return []

    async def fake_save_manual_topic(
        _app: AppContainer,
        topic: str,
        course_id: int,
    ) -> TopicMapping | None:
        calls.append(f"manual:{topic}:{course_id}")
        return TopicMapping(topic=topic, course_id=course_id, source=TopicSource.MANUAL)

    async def fake_get_confidence_ratings(
        _db: object,
        course_id: int,
    ) -> list[ConfidenceRating]:
        calls.append(f"confidence-list:{course_id}")
        return []

    async def fake_rate_confidence(
        _app: AppContainer,
        topic: str,
        course_id: int,
        rating: int,
    ) -> ConfidenceRating:
        calls.append(f"confidence-save:{topic}:{course_id}:{rating}")
        return ConfidenceRating(
            topic=topic,
            course_id=course_id,
            predicted=0.75,
            actual=None,
            rated_at="2026-05-26T12:00:00Z",
        )

    monkeypatch.setattr(topics_router, "get_course_topics", fake_get_course_topics)
    monkeypatch.setattr(topics_router, "save_manual_topic", fake_save_manual_topic)
    monkeypatch.setattr(topics_router, "get_confidence_ratings", fake_get_confidence_ratings)
    monkeypatch.setattr(topics_router, "rate_confidence", fake_rate_confidence)

    list_response = harness.client.get("/api/learning-paths/99/topics")
    manual_response = harness.client.post(
        "/api/learning-paths/99/topics",
        json={"topic": "Amortized analysis"},
        headers=csrf_headers(harness),
    )
    confidence_list_response = harness.client.get("/api/learning-paths/99/topics/confidence")
    confidence_save_response = harness.client.post(
        "/api/learning-paths/99/topics/confidence",
        json={"topic": "Graphs", "rating": 4},
        headers=csrf_headers(harness),
    )

    assert list_response.status_code == 403
    assert manual_response.status_code == 403
    assert confidence_list_response.status_code == 403
    assert confidence_save_response.status_code == 403
    assert calls == []


def test_extract_topics_rejects_cross_scope_content_source_before_service_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_app = FakeAppContainer(db=object())
    harness = build_harness(
        app_container=cast("AppContainer", fake_app),
        tenant=learning_path_tenant(12),
    )
    login(harness)
    stub_module_owners(monkeypatch, {99: "99"})
    calls: list[int] = []

    async def fake_extract_topics_from_lectures(
        _app: AppContainer,
        _db: object,
        course_id: int,
        *,
        force: bool = False,
    ) -> list[TopicMapping]:
        calls.append(course_id)
        return [TopicMapping(topic="Graphs", course_id=course_id, source=TopicSource.LECTURE)]

    monkeypatch.setattr(
        topics_router,
        "extract_topics_from_lectures",
        fake_extract_topics_from_lectures,
    )

    response = harness.client.post(
        "/api/learning-paths/12/topics/extract",
        json={"content_source_id": 99},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 403
    assert calls == []


def test_topic_request_validation_returns_422() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))
    login(harness)

    list_response = harness.client.get("/api/learning-paths/0/topics")
    extract_response = harness.client.post(
        "/api/learning-paths/12/topics/extract",
        json={"content_source_id": 0},
        headers=csrf_headers(harness),
    )
    confidence_response = harness.client.post(
        "/api/learning-paths/12/topics/confidence",
        json={"topic": "Graphs", "rating": 6},
        headers=csrf_headers(harness),
    )

    assert list_response.status_code == 422
    assert extract_response.status_code == 422
    assert confidence_response.status_code == 422
    assert list_response.json() == {"detail": {"code": "request.validation_failed", "params": {}}}


def test_topics_openapi_contract_is_visible() -> None:
    harness = build_harness(app_container=cast("AppContainer", FakeAppContainer(db=object())))

    openapi = harness.app.openapi()
    topics_path = "/api/learning-paths/{learning_path_id}/topics"
    confidence_path = f"{topics_path}/confidence"

    assert openapi["paths"][topics_path]["get"]["tags"] == ["topics"]
    assert openapi["paths"][topics_path]["get"]["operationId"] == "listTopics"
    assert openapi["paths"][topics_path]["post"]["operationId"] == "saveManualTopic"
    assert openapi["paths"][f"{topics_path}/extract"]["post"]["operationId"] == "extractTopics"
    assert openapi["paths"][confidence_path]["get"]["operationId"] == "listTopicConfidenceRatings"
    assert openapi["paths"][confidence_path]["post"]["operationId"] == "saveTopicConfidenceRating"


async def _seed_course(session: AsyncSession) -> None:
    """EP1 2026W's shape (#127): two lecture modules, both owned by learning path 12."""
    for module_id, episode_id, text in (
        (3022060, "ep-w1", "Schleifen und Verzweigungen"),
        (3022498, "ep-w2", "Arrays und Referenzen"),
    ):
        await session.execute(
            insert(lecture_modules).values(module_id=module_id, course_id="12", course_name="EP1")
        )
        await session.execute(
            insert(transcriptions).values(
                episode_id=episode_id, module_id=module_id, status="completed"
            )
        )
        await session.execute(
            insert(transcript_segments).values(
                episode_id=episode_id, segment_index=0, start_time=0.0, end_time=1.0, text=text
            )
        )
    await session.execute(insert(lecture_modules).values(module_id=2856855, course_id="99"))


@pytest.mark.postgres
async def test_topics_extracted_for_an_owned_module_are_listed_under_its_learning_path(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#127: module 3022498 is learning path 12's, and 3022498 != 12.

    The extraction reads both of the path's modules, and the topics are listed
    under the path the browser asks for.
    """
    extractor = MagicMock()
    extractor.extract_topics = AsyncMock(return_value=["Schleifen", "Arrays"])
    monkeypatch.setattr(
        "sophia.services.athena_topics.create_topic_extractor", lambda _app: extractor
    )

    async with db_harness(clean_engine) as harness:
        async with harness.seed() as session:
            await _seed_course(session)
        await harness.login()
        extracted = await harness.client.post(
            "/api/learning-paths/12/topics/extract",
            json={"content_source_id": 3022498},
            headers=harness.csrf_headers(),
        )
        listed = await harness.client.get("/api/learning-paths/12/topics")

    assert extracted.status_code == 200
    texts_sent = [call.args[0] for call in extractor.extract_topics.call_args_list]
    assert any("Schleifen und Verzweigungen" in text for text in texts_sent)
    assert any("Arrays und Referenzen" in text for text in texts_sent)
    assert listed.status_code == 200
    assert {(topic["topic"], topic["learning_path_id"]) for topic in listed.json()["topics"]} == {
        ("Schleifen", 12),
        ("Arrays", 12),
    }


@pytest.mark.postgres
@pytest.mark.parametrize(
    "content_source_id",
    [
        pytest.param(2856855, id="another-learning-paths-module"),
        pytest.param(4040404, id="module-with-no-recorded-owner"),
    ],
)
async def test_extraction_is_refused_for_a_module_the_learning_path_does_not_own(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    content_source_id: int,
) -> None:
    extract = AsyncMock(return_value=[])
    monkeypatch.setattr(topics_router, "extract_topics_from_lectures", extract)

    async with db_harness(clean_engine) as harness:
        async with harness.seed() as session:
            await _seed_course(session)
        await harness.login()
        response = await harness.client.post(
            "/api/learning-paths/12/topics/extract",
            json={"content_source_id": content_source_id},
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 403
    extract.assert_not_called()
