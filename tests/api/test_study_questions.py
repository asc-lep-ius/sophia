"""Question generation: discriminated union, provenance, and content language."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import aiosqlite
import pytest

from sophia.api import create_api_app
from sophia.api.routers import study_questions as questions_router
from sophia.api.sessions import SessionTenant
from sophia.config import Settings
from sophia.domain.learning import ContentLanguage, LearningPathSettings, StoredContentOrigin
from sophia.infra.persistence import run_migrations
from sophia.services.content_language import save_learning_path_settings
from sophia.services.study_questions import (
    FALLBACK_GENERATOR_REF,
    default_elaboration_policy,
    generate_and_store_questions,
    get_question,
)

from ._session_helpers import ApiHarness, build_harness, csrf_headers, login

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sophia.infra.di import AppContainer

LEARNING_PATH_ID = 12
SCHEMA_REF_PREFIX = "#/components/schemas/"


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: aiosqlite.Connection
    settings: Settings


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(":memory:")
    await connection.execute("PRAGMA foreign_keys=ON")
    await run_migrations(connection)
    yield connection
    await connection.close()


def build_logged_in_harness(container: FakeAppContainer) -> ApiHarness:
    harness = build_harness(
        app_container=cast("AppContainer", container),
        tenant=SessionTenant(
            org_id="tu-wien",
            learning_path_id=str(LEARNING_PATH_ID),
            cohort_id="cohort-a",
            role="student",
        ),
    )
    login(harness)
    return harness


def stub_prompts(monkeypatch: pytest.MonkeyPatch, prompts: list[str]) -> None:
    async def fake_generate(
        _app: object,
        _course_id: int,
        _topic: str,
        *,
        count: int = 3,
        difficulty: str = "explain",
    ) -> list[str]:
        return prompts[:count]

    monkeypatch.setattr(
        "sophia.services.study_questions.generate_study_questions",
        fake_generate,
    )


def test_question_union_discriminates_on_response_format() -> None:
    schemas = create_api_app().openapi()["components"]["schemas"]

    items = schemas["StudyQuestionListResponse"]["properties"]["questions"]["items"]
    union = schemas[items["$ref"].removeprefix(SCHEMA_REF_PREFIX)]
    variants = {ref["$ref"].removeprefix(SCHEMA_REF_PREFIX) for ref in union["oneOf"]}

    assert items["$ref"] == f"{SCHEMA_REF_PREFIX}Question"
    assert union["discriminator"]["propertyName"] == "kind"
    assert variants == {"OpenResponseQuestion", "MultipleChoiceQuestion", "ClozeQuestion"}


def test_only_the_free_response_variant_can_demand_elaboration() -> None:
    schemas = create_api_app().openapi()["components"]["schemas"]

    def policy_ref(variant: str) -> str:
        return schemas[variant]["properties"]["engagement_policy"]["$ref"]

    assert policy_ref("OpenResponseQuestion").endswith("ElaborationPolicy")
    assert policy_ref("MultipleChoiceQuestion").endswith("NoEngagementPolicy")
    assert policy_ref("ClozeQuestion").endswith("NoEngagementPolicy")


async def test_generated_questions_are_persisted_with_their_policy(
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The policy the server enforces is the one it issued, not one the client sends."""
    stub_prompts(monkeypatch, ["Why does a minimum cut bound maximum flow?"])
    container = FakeAppContainer(db=db, settings=Settings())

    questions = await generate_and_store_questions(
        cast("AppContainer", container),
        LEARNING_PATH_ID,
        "Graphs",
        count=1,
        content_language=ContentLanguage.DE,
        policy=default_elaboration_policy(min_elaboration_chars=80, min_prompt_dwell_ms=5000),
    )

    stored = await get_question(db, questions[0].id)
    assert stored is not None
    assert stored.elaboration_policy is not None
    assert stored.elaboration_policy.min_elaboration_chars == 80


async def test_generation_route_returns_provenance_and_resolved_language(
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await save_learning_path_settings(
        db,
        LearningPathSettings(
            course_id=LEARNING_PATH_ID,
            exam_language=ContentLanguage.EN,
            content_origin=StoredContentOrigin.TUWEL,
        ),
    )
    stub_prompts(monkeypatch, ["Why does a minimum cut bound maximum flow?"])
    harness = build_logged_in_harness(FakeAppContainer(db=db, settings=Settings()))

    response = harness.client.post(
        "/api/study/questions",
        json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 1},
        headers=csrf_headers(harness),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["content_language"] == "en"
    question = body["questions"][0]
    assert question["kind"] == "open_response"
    assert question["provenance"]["origin"] == "lms"
    assert question["provenance"]["generated_by"] == "model"
    assert question["provenance"]["verified_by"] is None
    assert question["translations"] == []


async def test_lang_query_overrides_the_paths_exam_language(
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await save_learning_path_settings(
        db,
        LearningPathSettings(
            course_id=LEARNING_PATH_ID,
            exam_language=ContentLanguage.DE,
            content_origin=StoredContentOrigin.TUWEL,
        ),
    )
    stub_prompts(monkeypatch, ["Warum begrenzt ein minimaler Schnitt den maximalen Fluss?"])
    harness = build_logged_in_harness(FakeAppContainer(db=db, settings=Settings()))

    response = harness.client.post(
        "/api/study/questions?lang=en",
        json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 1},
        headers=csrf_headers(harness),
    )

    assert response.json()["content_language"] == "en"


async def test_template_fallback_is_not_attributed_to_a_model(
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provenance must not credit an LLM for a question a template produced."""
    from sophia.domain.errors import TopicExtractionError

    async def failing_generate(*_args: object, **_kwargs: object) -> list[str]:
        raise TopicExtractionError("no llm configured")

    monkeypatch.setattr(
        "sophia.services.study_questions.generate_study_questions",
        failing_generate,
    )
    harness = build_logged_in_harness(FakeAppContainer(db=db, settings=Settings()))

    response = harness.client.post(
        "/api/study/questions",
        json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 2},
        headers=csrf_headers(harness),
    )

    generators = {
        question["provenance"]["generator_ref"] for question in response.json()["questions"]
    }
    assert generators == {FALLBACK_GENERATOR_REF}


async def test_generation_rejects_out_of_scope_learning_paths(
    db: aiosqlite.Connection,
) -> None:
    harness = build_logged_in_harness(FakeAppContainer(db=db, settings=Settings()))

    response = harness.client.post(
        "/api/study/questions",
        json={"learning_path_id": 99, "topic": "Graphs", "count": 1},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 403


def test_generation_requires_authentication() -> None:
    harness = build_harness(
        app_container=cast(
            "AppContainer",
            FakeAppContainer(db=cast("aiosqlite.Connection", object()), settings=Settings()),
        ),
    )

    response = harness.client.post(
        "/api/study/questions",
        json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 1},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert response.status_code == 401


def test_question_routes_are_tagged_and_named_for_the_generated_client() -> None:
    paths = create_api_app().openapi()["paths"]

    assert paths["/api/study/questions"]["post"]["operationId"] == "generateStudyQuestions"
    assert paths["/api/study/attempts"]["post"]["operationId"] == "submitStudyAttempt"
    assert questions_router.router.tags == ["study"]


async def test_a_question_without_provenance_is_never_served(
    db: aiosqlite.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short list the client cannot distinguish from a small one is worse than an error."""
    stub_prompts(monkeypatch, ["Why does a minimum cut bound maximum flow?"])

    async def provenance_lost(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(questions_router, "get_provenance_map", provenance_lost)
    harness = build_logged_in_harness(FakeAppContainer(db=db, settings=Settings()))

    response = harness.client.post(
        "/api/study/questions",
        json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 1},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "athena.failed"
