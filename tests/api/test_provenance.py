"""Provenance is present, honest, and source-agnostic in the published contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiosqlite
import pytest

from sophia.api import create_api_app
from sophia.api.provenance import api_provenance
from sophia.domain.learning import (
    ContentKind,
    ContentProvenance,
    ProvenanceAgent,
    SourceSpan,
    StoredContentOrigin,
)
from sophia.infra.persistence import run_migrations
from sophia.services.provenance import (
    get_provenance_map,
    learner_authored,
    record_provenance,
    unverified_provenance,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

SCHEMA_REF_PREFIX = "#/components/schemas/"
CONTENT_BEARING_SCHEMAS = (
    "StudyFlashcardItemResponse",
    "OpenResponseQuestion",
)


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(":memory:")
    await connection.execute("PRAGMA foreign_keys=ON")
    await run_migrations(connection)
    yield connection
    await connection.close()


def model_provenance(**overrides: Any) -> ContentProvenance:
    defaults: dict[str, Any] = {
        "content_kind": ContentKind.QUESTION,
        "content_id": "question-1",
        "course_id": 12,
        "origin": StoredContentOrigin.TUWEL,
        "generated_by": ProvenanceAgent.MODEL,
        "generator_ref": "github:openai/gpt-4o",
        "generated_at": "2026-05-26T14:00:00+00:00",
    }
    return ContentProvenance(**{**defaults, **overrides})


def test_content_bearing_responses_carry_a_provenance_block() -> None:
    schemas = create_api_app().openapi()["components"]["schemas"]

    missing = [
        name for name in CONTENT_BEARING_SCHEMAS if "provenance" not in schemas[name]["properties"]
    ]

    assert missing == []


def test_provenance_carries_the_reserved_origin_discriminator() -> None:
    schemas = create_api_app().openapi()["components"]["schemas"]

    origin_ref = schemas["Provenance"]["properties"]["origin"]["$ref"]

    assert origin_ref == f"{SCHEMA_REF_PREFIX}ContentOrigin"
    assert schemas["ContentOrigin"]["enum"] == ["lms"]


def test_origin_discriminator_never_names_the_upstream_vendor() -> None:
    """Adding a source must not break the client, and must not leak a product name."""
    schemas = create_api_app().openapi()["components"]["schemas"]

    assert StoredContentOrigin.TUWEL.value not in schemas["ContentOrigin"]["enum"]
    assert api_provenance(model_provenance()).origin.value == "lms"


async def test_unverified_generated_content_has_a_null_verifier(
    db: aiosqlite.Connection,
) -> None:
    await record_provenance(db, model_provenance())

    stored = await get_provenance_map(db, ContentKind.QUESTION, ["question-1"])

    assert stored["question-1"].verified_by is None
    assert api_provenance(stored["question-1"]).verified_by is None


async def test_verified_content_is_distinguishable(db: aiosqlite.Connection) -> None:
    await record_provenance(
        db,
        model_provenance(verified_by="instructor-1", verified_at="2026-05-27T09:00:00+00:00"),
    )

    stored = await get_provenance_map(db, ContentKind.QUESTION, ["question-1"])

    assert stored["question-1"].verified_by == "instructor-1"
    assert await unverified_provenance(db, 12) == []


async def test_unverified_query_ignores_learner_authored_content(
    db: aiosqlite.Connection,
) -> None:
    """Instructor triage is about what a model produced, not what a learner wrote."""
    await record_provenance(
        db,
        learner_authored(
            ContentKind.FLASHCARD,
            "flashcard-1",
            12,
            generated_at="2026-05-26T14:00:00+00:00",
        ),
    )
    await record_provenance(db, model_provenance())

    pending = await unverified_provenance(db, 12)

    assert [record.content_id for record in pending] == ["question-1"]


async def test_source_spans_round_trip(db: aiosqlite.Connection) -> None:
    await record_provenance(
        db,
        model_provenance(
            source_spans=(
                SourceSpan(content_item_id="item-1", start_char=10, end_char=90),
                SourceSpan(content_item_id="item-2", start_ms=1000, end_ms=4000, excerpt="…"),
            ),
        ),
    )

    stored = await get_provenance_map(db, ContentKind.QUESTION, ["question-1"])

    spans = stored["question-1"].source_spans
    assert [span.content_item_id for span in spans] == ["item-1", "item-2"]
    assert spans[0].start_char == 10
    assert spans[1].end_ms == 4000


async def test_re_recording_provenance_replaces_rather_than_duplicates_spans(
    db: aiosqlite.Connection,
) -> None:
    await record_provenance(
        db,
        model_provenance(source_spans=(SourceSpan(content_item_id="item-1"),)),
    )
    await record_provenance(
        db,
        model_provenance(source_spans=(SourceSpan(content_item_id="item-2"),)),
    )

    stored = await get_provenance_map(db, ContentKind.QUESTION, ["question-1"])

    assert [span.content_item_id for span in stored["question-1"].source_spans] == ["item-2"]
    cursor = await db.execute("SELECT COUNT(*) FROM content_provenance")
    assert await cursor.fetchone() == (1,)


async def test_provenance_lookup_of_nothing_touches_no_rows(db: aiosqlite.Connection) -> None:
    assert await get_provenance_map(db, ContentKind.QUESTION, []) == {}
