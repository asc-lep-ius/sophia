"""Question generation: discriminated union, provenance, and content language."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from sophia.api import create_api_app
from sophia.api.routers import study_questions as questions_router
from sophia.domain.learning import ContentLanguage, LearningPathSettings, StoredContentOrigin
from sophia.services.athena_session import start_study_session
from sophia.services.content_language import save_learning_path_settings
from sophia.services.study_questions import (
    FALLBACK_GENERATOR_REF,
    default_elaboration_policy,
    generate_and_store_questions,
    get_question,
)

from ._db_harness import DbContainer, db_harness, learning_path_tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from sophia.infra.di import AppContainer


pytestmark = pytest.mark.postgres

LEARNING_PATH_ID = 12
SCHEMA_REF_PREFIX = "#/components/schemas/"


def stub_prompts(monkeypatch: pytest.MonkeyPatch, prompts: list[str]) -> None:
    async def fake_generate(
        _app: object,
        _session: object,
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


def test_question_routes_are_tagged_and_named_for_the_generated_client() -> None:
    paths = create_api_app().openapi()["paths"]

    assert paths["/api/study/questions"]["post"]["operationId"] == "generateStudyQuestions"
    assert paths["/api/study/attempts"]["post"]["operationId"] == "submitStudyAttempt"
    assert questions_router.router.tags == ["study"]


async def test_generated_questions_are_persisted_with_their_policy(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The policy the server enforces is the one it issued, not one the client sends."""
    stub_prompts(monkeypatch, ["Why does a minimum cut bound maximum flow?"])
    container = DbContainer(session_factory=session_factory)

    questions = await generate_and_store_questions(
        cast("AppContainer", container),
        db,
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
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_prompts(monkeypatch, ["Why does a minimum cut bound maximum flow?"])

    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await save_learning_path_settings(
                session,
                LearningPathSettings(
                    course_id=LEARNING_PATH_ID,
                    exam_language=ContentLanguage.EN,
                    content_origin=StoredContentOrigin.TUWEL,
                ),
            )
        await harness.login()

        response = await harness.client.post(
            "/api/study/questions",
            json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 1},
            headers=harness.csrf_headers(),
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
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_prompts(monkeypatch, ["Warum begrenzt ein minimaler Schnitt den maximalen Fluss?"])

    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await save_learning_path_settings(
                session,
                LearningPathSettings(
                    course_id=LEARNING_PATH_ID,
                    exam_language=ContentLanguage.DE,
                    content_origin=StoredContentOrigin.TUWEL,
                ),
            )
        await harness.login()

        response = await harness.client.post(
            "/api/study/questions?lang=en",
            json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 1},
            headers=harness.csrf_headers(),
        )

    assert response.json()["content_language"] == "en"


async def test_template_fallback_is_not_attributed_to_a_model(
    clean_engine: AsyncEngine,
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

    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        await harness.login()
        response = await harness.client.post(
            "/api/study/questions",
            json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 2},
            headers=harness.csrf_headers(),
        )

    generators = {
        question["provenance"]["generator_ref"] for question in response.json()["questions"]
    }
    assert generators == {FALLBACK_GENERATOR_REF}


async def test_generation_rejects_out_of_scope_learning_paths(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        await harness.login()
        response = await harness.client.post(
            "/api/study/questions",
            json={"learning_path_id": 99, "topic": "Graphs", "count": 1},
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 403


async def test_generation_requires_authentication(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine) as harness:
        response = await harness.client.post(
            "/api/study/questions",
            json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 1},
            headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
        )

    assert response.status_code == 401


async def test_a_question_without_provenance_is_never_served(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short list the client cannot distinguish from a small one is worse than an error."""
    stub_prompts(monkeypatch, ["Why does a minimum cut bound maximum flow?"])

    async def provenance_lost(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(questions_router, "get_provenance_map", provenance_lost)

    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        await harness.login()
        response = await harness.client.post(
            "/api/study/questions",
            json={"learning_path_id": LEARNING_PATH_ID, "topic": "Graphs", "count": 1},
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "athena.failed"


async def test_generation_refuses_to_bind_a_batch_to_another_learners_session(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the ownership check a learner sharing a learning path could
    inject cards into somebody else's deck."""
    stub_prompts(monkeypatch, ["Why does a minimum cut bound maximum flow?"])

    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            other_session = await start_study_session(
                session, LEARNING_PATH_ID, "Graphs", user_id="somebody-else"
            )
        await harness.login("learner")

        response = await harness.client.post(
            "/api/study/questions",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "topic": "Graphs",
                "count": 1,
                "session_id": other_session.id,
            },
            headers=harness.csrf_headers(),
        )
        stored = await harness.client.get(f"/api/study/sessions/{other_session.id}/questions")

    assert response.status_code == 404
    assert stored.status_code == 404


async def test_generation_binds_a_batch_to_the_learners_own_session(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_prompts(monkeypatch, ["Why does a minimum cut bound maximum flow?"])

    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            own_session = await start_study_session(
                session, LEARNING_PATH_ID, "Graphs", user_id="learner"
            )
        await harness.login("learner")

        response = await harness.client.post(
            "/api/study/questions",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "topic": "Graphs",
                "count": 1,
                "session_id": own_session.id,
            },
            headers=harness.csrf_headers(),
        )
        stored = await harness.client.get(f"/api/study/sessions/{own_session.id}/questions")

    assert response.status_code == 200
    assert stored.status_code == 200
    assert len(stored.json()["questions"]) == 1
    assert stored.json()["attempted_question_ids"] == []
