"""Provenance persistence for generated learning content.

Provenance lives in its own table keyed by ``(content_kind, content_id)`` rather
than as columns on every content table, so a new content kind inherits the audit
trail without another migration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sophia.domain.learning import (
    ContentKind,
    ContentProvenance,
    ProvenanceAgent,
    SourceSpan,
    StoredContentOrigin,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import aiosqlite

_PROVENANCE_COLUMNS = (
    "id, content_kind, content_id, course_id, content_origin, generated_by, "
    "generator_ref, generated_at, verified_by, verified_at"
)


async def record_provenance(
    db: aiosqlite.Connection,
    provenance: ContentProvenance,
    *,
    commit: bool = True,
) -> None:
    """Upsert a provenance record and replace its source spans."""
    cursor = await db.execute(
        "INSERT INTO content_provenance ("
        "content_kind, content_id, course_id, content_origin, generated_by, "
        "generator_ref, generated_at, verified_by, verified_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(content_kind, content_id) DO UPDATE SET "
        "course_id = excluded.course_id, "
        "content_origin = excluded.content_origin, "
        "generated_by = excluded.generated_by, "
        "generator_ref = excluded.generator_ref, "
        "generated_at = excluded.generated_at, "
        "verified_by = excluded.verified_by, "
        "verified_at = excluded.verified_at "
        "RETURNING id",
        (
            provenance.content_kind.value,
            provenance.content_id,
            provenance.course_id,
            provenance.origin.value,
            provenance.generated_by.value,
            provenance.generator_ref,
            provenance.generated_at or _now(),
            provenance.verified_by,
            provenance.verified_at,
        ),
    )
    row = cast("tuple[int, ...] | None", await cursor.fetchone())
    if row is None:
        msg = "provenance upsert returned no row"
        raise RuntimeError(msg)
    provenance_id = row[0]

    await db.execute("DELETE FROM content_source_spans WHERE provenance_id = ?", (provenance_id,))
    for span in provenance.source_spans:
        await db.execute(
            "INSERT INTO content_source_spans ("
            "provenance_id, content_item_id, start_char, end_char, start_ms, end_ms, excerpt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                provenance_id,
                span.content_item_id,
                span.start_char,
                span.end_char,
                span.start_ms,
                span.end_ms,
                span.excerpt,
            ),
        )
    if commit:
        await db.commit()


async def get_provenance_map(
    db: aiosqlite.Connection,
    content_kind: ContentKind,
    content_ids: Iterable[str],
) -> dict[str, ContentProvenance]:
    """Load provenance for many content items, keyed by content id."""
    ids = list(dict.fromkeys(content_ids))
    if not ids:
        return {}

    placeholders = ", ".join("?" for _ in ids)
    cursor = await db.execute(
        # Interpolation is a constant column list plus generated placeholders.
        f"SELECT {_PROVENANCE_COLUMNS} FROM content_provenance "
        f"WHERE content_kind = ? AND content_id IN ({placeholders})",
        (content_kind.value, *ids),
    )
    rows = cast("Sequence[tuple[object, ...]]", await cursor.fetchall())
    spans = await _source_spans_by_provenance(db, [int(cast("int", row[0])) for row in rows])
    return {
        str(row[2]): _row_to_provenance(row, spans.get(int(cast("int", row[0])), ()))
        for row in rows
    }


async def unverified_provenance(
    db: aiosqlite.Connection,
    course_id: int,
) -> list[ContentProvenance]:
    """Load model-generated content for a learning path that nobody has checked."""
    cursor = await db.execute(
        f"SELECT {_PROVENANCE_COLUMNS} FROM content_provenance "
        "WHERE course_id = ? AND generated_by = ? AND verified_by IS NULL "
        "ORDER BY generated_at DESC",
        (course_id, ProvenanceAgent.MODEL.value),
    )
    rows = cast("Sequence[tuple[object, ...]]", await cursor.fetchall())
    spans = await _source_spans_by_provenance(db, [int(cast("int", row[0])) for row in rows])
    return [_row_to_provenance(row, spans.get(int(cast("int", row[0])), ())) for row in rows]


def learner_authored(
    content_kind: ContentKind,
    content_id: str,
    course_id: int,
    *,
    generated_at: str,
) -> ContentProvenance:
    """Provenance for content a learner wrote themselves.

    ``verified_by`` stays null: writing a card is authorship, not verification.
    Only an instructor sign-off in a later phase fills that field in.
    """
    return ContentProvenance(
        content_kind=content_kind,
        content_id=content_id,
        course_id=course_id,
        origin=StoredContentOrigin.TUWEL,
        generated_by=ProvenanceAgent.LEARNER,
        generated_at=generated_at or _now(),
    )


def _row_to_provenance(
    row: tuple[object, ...],
    spans: tuple[SourceSpan, ...],
) -> ContentProvenance:
    return ContentProvenance(
        content_kind=ContentKind(str(row[1])),
        content_id=str(row[2]),
        course_id=int(cast("int", row[3])),
        origin=StoredContentOrigin(str(row[4])),
        generated_by=ProvenanceAgent(str(row[5])),
        generator_ref=None if row[6] is None else str(row[6]),
        generated_at=str(row[7] or ""),
        verified_by=None if row[8] is None else str(row[8]),
        verified_at=None if row[9] is None else str(row[9]),
        source_spans=spans,
    )


async def _source_spans_by_provenance(
    db: aiosqlite.Connection,
    provenance_ids: Sequence[int],
) -> dict[int, tuple[SourceSpan, ...]]:
    if not provenance_ids:
        return {}

    placeholders = ", ".join("?" for _ in provenance_ids)
    cursor = await db.execute(
        "SELECT provenance_id, content_item_id, start_char, end_char, start_ms, end_ms, excerpt "
        f"FROM content_source_spans WHERE provenance_id IN ({placeholders}) ORDER BY id",
        tuple(provenance_ids),
    )
    grouped: dict[int, list[SourceSpan]] = {}
    for row in cast("Sequence[tuple[object, ...]]", await cursor.fetchall()):
        grouped.setdefault(int(cast("int", row[0])), []).append(
            SourceSpan(
                content_item_id=str(row[1]),
                start_char=None if row[2] is None else int(cast("int", row[2])),
                end_char=None if row[3] is None else int(cast("int", row[3])),
                start_ms=None if row[4] is None else int(cast("int", row[4])),
                end_ms=None if row[5] is None else int(cast("int", row[5])),
                excerpt=None if row[6] is None else str(row[6]),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _now() -> str:
    return datetime.now(UTC).isoformat()
