"""Question generation: discriminated union, provenance, and content language."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import insert, select

from sophia.api import create_api_app
from sophia.api.routers import study_questions as questions_router
from sophia.domain.errors import TopicExtractionError
from sophia.domain.learning import ContentLanguage, LearningPathSettings, StoredContentOrigin
from sophia.domain.models import KnowledgeChunk
from sophia.infra.schema import content_provenance, content_source_spans, lecture_downloads
from sophia.services import study_questions as study_questions_service
from sophia.services.athena_session import start_study_session
from sophia.services.athena_study import GroundedQuestion
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
MODEL_GENERATOR_REF = "test-provider:test-model"
LECTURE_CHUNK = KnowledgeChunk(
    chunk_id="ep-001_0",
    episode_id="ep-001",
    chunk_index=0,
    text="Every s-t cut has capacity at least the value of any flow from s to t.",
    start_time=12.5,
    end_time=27.0,
)


def stub_prompts(
    monkeypatch: pytest.MonkeyPatch,
    prompts: list[str],
    *,
    sources: tuple[KnowledgeChunk, ...] = (),
) -> None:
    async def fake_generate(
        _app: object,
        _session: object,
        _course_id: int,
        _topic: str,
        *,
        count: int = 3,
        difficulty: str = "explain",
    ) -> list[GroundedQuestion]:
        return [GroundedQuestion(prompt=prompt, sources=sources) for prompt in prompts[:count]]

    monkeypatch.setattr(
        "sophia.services.study_questions.generate_grounded_questions",
        fake_generate,
    )


def stub_lecture_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[KnowledgeChunk],
    generated: list[str | Exception],
) -> None:
    """Replace the embedder, the vector store and the model, and nothing else.

    The episode lookup, the grounding and the provenance write stay real, so a
    span can only reach the database the way a synced course's would.
    """
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1, 0.2]
    store = MagicMock()
    store.search.return_value = [(chunk, 0.9) for chunk in chunks]
    extractor = MagicMock()
    extractor.generate_question = AsyncMock(side_effect=generated)

    monkeypatch.setattr(
        "sophia.services.athena_study._get_or_create_embedder", lambda _config: embedder
    )
    monkeypatch.setattr("sophia.services.athena_study._get_or_create_store", lambda _s: store)
    monkeypatch.setattr(
        "sophia.services.athena_study._create_topic_extractor", lambda _app: extractor
    )
    monkeypatch.setattr(study_questions_service, "_generator_ref", lambda _app: MODEL_GENERATOR_REF)


async def stored_spans(
    db: AsyncSession, question_id: str
) -> list[tuple[str, int | None, int | None, str | None]]:
    """The source spans joined to one question's provenance record."""
    rows = await db.execute(
        select(
            content_source_spans.c.content_item_id,
            content_source_spans.c.start_ms,
            content_source_spans.c.end_ms,
            content_source_spans.c.excerpt,
        )
        .join(content_provenance, content_provenance.c.id == content_source_spans.c.provenance_id)
        .where(
            content_provenance.c.content_kind == "question",
            content_provenance.c.content_id == question_id,
        )
        .order_by(content_source_spans.c.id)
    )
    return [tuple(row) for row in rows.all()]


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


async def test_a_grounded_question_records_the_lecture_chunks_it_came_from(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reveal shows these spans, so the proof is in the rows, not the copy (#109).

    The second question is the template padding a short model batch: nothing
    grounded it, and its provenance must say so rather than borrow the first
    question's material or credit the model with it.
    """
    stub_lecture_retrieval(
        monkeypatch,
        [LECTURE_CHUNK],
        ["Why does a minimum cut bound maximum flow?", TopicExtractionError("model gave up")],
    )
    await db.execute(
        insert(lecture_downloads).values(
            episode_id=LECTURE_CHUNK.episode_id,
            module_id=LEARNING_PATH_ID,
            title="Lecture 3: Flows",
            track_url="https://example.com/a.mp3",
            track_mimetype="audio/mpeg",
            status="completed",
        )
    )
    container = DbContainer(session_factory=session_factory)

    grounded, padded = await generate_and_store_questions(
        cast("AppContainer", container),
        db,
        LEARNING_PATH_ID,
        "Graphs",
        count=2,
        content_language=ContentLanguage.EN,
        policy=default_elaboration_policy(min_elaboration_chars=80, min_prompt_dwell_ms=5000),
    )

    assert await stored_spans(db, grounded.id) == [
        ("ep-001", 12_500, 27_000, LECTURE_CHUNK.text),
    ]
    assert await stored_spans(db, padded.id) == []
    provenance_rows = await db.execute(
        select(content_provenance.c.content_id, content_provenance.c.generator_ref)
    )
    generator_refs = {row.content_id: row.generator_ref for row in provenance_rows}
    assert generator_refs == {
        grounded.id: MODEL_GENERATOR_REF,
        padded.id: FALLBACK_GENERATOR_REF,
    }


async def test_a_question_with_no_lecture_data_records_no_spans(
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without synced lectures every card is the template, and is free recall."""
    monkeypatch.setattr(study_questions_service, "_generator_ref", lambda _app: MODEL_GENERATOR_REF)
    container = DbContainer(session_factory=session_factory)

    questions = await generate_and_store_questions(
        cast("AppContainer", container),
        db,
        LEARNING_PATH_ID,
        "Graphs",
        count=1,
        content_language=ContentLanguage.EN,
        policy=default_elaboration_policy(min_elaboration_chars=80, min_prompt_dwell_ms=5000),
    )

    assert await stored_spans(db, questions[0].id) == []
    generator_ref = (await db.execute(select(content_provenance.c.generator_ref))).scalar_one()
    assert generator_ref == FALLBACK_GENERATOR_REF


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

    async def failing_generate(*_args: object, **_kwargs: object) -> list[GroundedQuestion]:
        raise TopicExtractionError("no llm configured")

    monkeypatch.setattr(
        "sophia.services.study_questions.generate_grounded_questions",
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
    stub_prompts(
        monkeypatch, ["Why does a minimum cut bound maximum flow?"], sources=(LECTURE_CHUNK,)
    )

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
    # What the study card reveals: the deck read back carries the material.
    [span] = stored.json()["questions"][0]["provenance"]["source_spans"]
    assert span["excerpt"] == LECTURE_CHUNK.text
