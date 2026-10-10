"""Studying and searching a course's processed lectures through the real API (#129).

The routes, the scoping queries, the provenance writes and the read-back all
run against Postgres. Only what the API cannot have in a test run is replaced:
the embedding model, the vector store and the question model. The store fake
filters by episode the way chromadb's ``where`` does, so a search that forgot
its scope would return the other course's chunk, which is ranked first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import insert, select

from sophia.domain.errors import EmbeddingError
from sophia.domain.models import KnowledgeChunk
from sophia.infra.schema import content_provenance, lecture_modules, transcriptions
from sophia.services import athena_study, hermes_index
from sophia.services import study_questions as study_questions_service
from sophia.services.athena_session import start_study_session
from sophia.services.study_questions import FALLBACK_QUESTION

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from ._db_harness import DbHarness

pytestmark = pytest.mark.postgres

COURSE_ID = 82774
WINTER_MODULE_ID = 3022060
OTHER_COURSE_ID = 78417
OTHER_MODULE_ID = 2856855
TOPIC = "Primitive Datentypen"
MODEL_REF = "test-provider:test-model"
GENERATED = "Warum hat eine Variable eines primitiven Datentyps immer einen Wert?"

FIRST_LECTURE = ("3ad1d746", "Vorlesung - VU vom 2026-10-02")
SECOND_LECTURE = ("6a0995b4", "Vorlesung - VU vom 2026-10-06")
OTHER_COURSE_LECTURE = ("72a8f98c", "Vorlesung - VU vom 2026-06-15")

SECOND_LECTURE_CHUNK = KnowledgeChunk(
    chunk_id=f"{SECOND_LECTURE[0]}_212",
    episode_id=SECOND_LECTURE[0],
    chunk_index=212,
    text="Sobald Sie Variablen vom primitiven Datentyp haben, haben die immer einen Wert.",
    start_time=737.67,
    end_time=748.2,
)
OTHER_COURSE_CHUNK = KnowledgeChunk(
    chunk_id=f"{OTHER_COURSE_LECTURE[0]}_3",
    episode_id=OTHER_COURSE_LECTURE[0],
    chunk_index=3,
    text="Primitive Datentypen, letztes Semester.",
    start_time=12.0,
    end_time=20.0,
)


@dataclass
class ScopedStore:
    """A knowledge store that answers only from the episodes it is asked about."""

    chunks: list[KnowledgeChunk]
    searched: list[list[str] | None] = field(default_factory=list[list[str] | None])

    def search(
        self,
        query_embedding: list[float],
        *,
        n_results: int = 5,
        episode_ids: list[str] | None = None,
        source_filter: str | None = None,
    ) -> list[tuple[KnowledgeChunk, float]]:
        self.searched.append(episode_ids)
        in_scope = [
            chunk for chunk in self.chunks if episode_ids is None or chunk.episode_id in episode_ids
        ]
        return [(chunk, 0.87) for chunk in in_scope[:n_results]]


def use_index(
    monkeypatch: pytest.MonkeyPatch,
    store: ScopedStore,
    *,
    embed_error: Exception | None = None,
) -> None:
    """Install the process's query embedder and store, the way the API holds them."""
    embedder = MagicMock()
    if embed_error is None:
        embedder.embed_query.return_value = [0.1, 0.2]
    else:
        embedder.embed_query.side_effect = embed_error
    monkeypatch.setattr(hermes_index, "_query_embedder_cache", embedder)
    monkeypatch.setattr(hermes_index, "_store_cache", store)
    extractor = MagicMock()
    extractor.generate_question = AsyncMock(return_value=GENERATED)
    monkeypatch.setattr(athena_study, "_create_topic_extractor", lambda _app: extractor)
    monkeypatch.setattr(study_questions_service, "_generator_ref", lambda _app: MODEL_REF)


async def seed_lectures(session: AsyncSession) -> None:
    """EP1 2026W's lecture series, and last semester's, owned by another course."""
    await session.execute(
        insert(lecture_modules).values(
            [
                {"module_id": WINTER_MODULE_ID, "course_id": str(COURSE_ID)},
                {"module_id": OTHER_MODULE_ID, "course_id": str(OTHER_COURSE_ID)},
            ]
        )
    )
    await session.execute(
        insert(transcriptions).values(
            [
                {
                    "episode_id": episode_id,
                    "module_id": module_id,
                    "title": title,
                    "status": "completed",
                }
                for (episode_id, title), module_id in (
                    (FIRST_LECTURE, WINTER_MODULE_ID),
                    (SECOND_LECTURE, WINTER_MODULE_ID),
                    (OTHER_COURSE_LECTURE, OTHER_MODULE_ID),
                )
            ]
        )
    )


async def start_deck(harness: DbHarness) -> tuple[int, dict[str, object]]:
    """Start a session on the topic, generate its deck, and read the deck back."""
    async with harness.seed() as session:
        await seed_lectures(session)
        study_session = await start_study_session(session, COURSE_ID, TOPIC, user_id="learner")
    await harness.login("learner")
    generated = await harness.client.post(
        "/api/study/questions",
        json={
            "learning_path_id": COURSE_ID,
            "topic": TOPIC,
            "count": 2,
            "session_id": study_session.id,
        },
        headers=harness.csrf_headers(),
    )
    assert generated.status_code == 200, generated.text
    deck = await harness.client.get(f"/api/study/sessions/{study_session.id}/questions")
    assert deck.status_code == 200
    return study_session.id, deck.json()


async def test_a_card_from_the_second_lecture_reveals_its_excerpt_lecture_and_timestamp(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 1: the question is generated from the lecture, and the reveal says where."""
    store = ScopedStore([OTHER_COURSE_CHUNK, SECOND_LECTURE_CHUNK])
    use_index(monkeypatch, store)

    async with db_harness(clean_engine, tenant=learning_path_tenant(COURSE_ID)) as harness:
        _session_id, deck = await start_deck(harness)

    questions = deck["questions"]
    assert isinstance(questions, list)
    card = questions[0]
    assert card["prompt"] == GENERATED
    assert card["fallback_reason"] is None
    assert card["provenance"]["generator_ref"] == MODEL_REF
    assert card["provenance"]["source_spans"] == [
        {
            "content_item_id": SECOND_LECTURE[0],
            "content_item_title": SECOND_LECTURE[1],
            "start_char": None,
            "end_char": None,
            "start_ms": 737_670,
            "end_ms": 748_200,
            "excerpt": SECOND_LECTURE_CHUNK.text,
        }
    ]


async def test_retrieval_only_reads_the_lectures_the_selected_course_owns(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ScopedStore([OTHER_COURSE_CHUNK, SECOND_LECTURE_CHUNK])
    use_index(monkeypatch, store)

    async with db_harness(clean_engine, tenant=learning_path_tenant(COURSE_ID)) as harness:
        await start_deck(harness)

    assert [sorted(scope or []) for scope in store.searched] == [
        sorted([FIRST_LECTURE[0], SECOND_LECTURE[0]])
    ]


async def test_an_unreadable_index_falls_back_to_the_template_and_says_why(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ScopedStore([SECOND_LECTURE_CHUNK])
    use_index(
        monkeypatch,
        store,
        embed_error=EmbeddingError("CUDA error: no kernel image is available for execution"),
    )

    async with db_harness(clean_engine, tenant=learning_path_tenant(COURSE_ID)) as harness:
        _session_id, deck = await start_deck(harness)
        async with harness.seed() as session:
            refs = (await session.scalars(select(content_provenance.c.generator_ref))).all()

    questions = deck["questions"]
    assert isinstance(questions, list)
    assert [(card["prompt"], card["fallback_reason"]) for card in questions] == [
        (FALLBACK_QUESTION.format(topic=TOPIC), "index_unavailable"),
    ] * 2
    assert all(card["provenance"]["source_spans"] == [] for card in questions)
    # Not credited to the model, and the reason survives the read-back.
    assert refs == ["fallback-template:index-unavailable"] * 2


async def search(harness: DbHarness, content_source_id: int) -> tuple[int, dict[str, object]]:
    response = await harness.client.post(
        "/api/search",
        json={
            "content_source_id": content_source_id,
            "learning_path_id": COURSE_ID,
            "query": "primitiver Datentyp hat immer einen Wert",
            "source_filter": "transcript",
        },
        headers=harness.csrf_headers(),
    )
    return response.status_code, response.json()


async def test_search_names_the_lecture_and_timestamp_of_a_spoken_phrase(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ScopedStore([OTHER_COURSE_CHUNK, SECOND_LECTURE_CHUNK])
    use_index(monkeypatch, store)

    async with db_harness(clean_engine, tenant=learning_path_tenant(COURSE_ID)) as harness:
        async with harness.seed() as session:
            await seed_lectures(session)
        await harness.login("learner")
        status, body = await search(harness, WINTER_MODULE_ID)

    assert status == 200
    results = body["results"]
    assert isinstance(results, list)
    first = results[0]
    assert (first["content_item_id"], first["title"], first["start_time"]) == (
        SECOND_LECTURE[0],
        SECOND_LECTURE[1],
        737.67,
    )
    assert [result["content_item_id"] for result in results] == [SECOND_LECTURE[0]]


async def test_search_says_the_index_is_unavailable_rather_than_failing(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_index(
        monkeypatch,
        ScopedStore([SECOND_LECTURE_CHUNK]),
        embed_error=EmbeddingError("chromadb not installed"),
    )

    async with db_harness(clean_engine, tenant=learning_path_tenant(COURSE_ID)) as harness:
        async with harness.seed() as session:
            await seed_lectures(session)
        await harness.login("learner")
        status, body = await search(harness, WINTER_MODULE_ID)

    assert status == 503
    assert body == {"detail": {"code": "lecture_index.unavailable", "params": {}}}


async def test_search_never_reads_a_series_another_course_owns(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ScopedStore([OTHER_COURSE_CHUNK])
    use_index(monkeypatch, store)

    async with db_harness(clean_engine, tenant=learning_path_tenant(COURSE_ID)) as harness:
        async with harness.seed() as session:
            await seed_lectures(session)
        await harness.login("learner")
        status, _body = await search(harness, OTHER_MODULE_ID)

    assert status == 403
    assert store.searched == []
