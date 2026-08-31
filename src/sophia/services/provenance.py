"""Provenance persistence for generated learning content.

Provenance lives in its own table keyed by ``(content_kind, content_id)`` rather
than as columns on every content table, so a new content kind inherits the audit
trail without another migration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.domain.learning import (
    ContentKind,
    ContentProvenance,
    ProvenanceAgent,
    SourceSpan,
    StoredContentOrigin,
)
from sophia.infra.schema import content_provenance, content_source_spans

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession


async def record_provenance(
    session: AsyncSession,
    provenance: ContentProvenance,
) -> None:
    """Upsert a provenance record and replace its source spans."""
    values = {
        "content_kind": provenance.content_kind.value,
        "content_id": provenance.content_id,
        "course_id": provenance.course_id,
        "content_origin": provenance.origin.value,
        "generated_by": provenance.generated_by.value,
        "generator_ref": provenance.generator_ref,
        "generated_at": _as_timestamp(provenance.generated_at),
        "verified_by": provenance.verified_by,
        "verified_at": _as_timestamp(provenance.verified_at),
    }
    statement = pg_insert(content_provenance).values(**values)
    upsert = statement.on_conflict_do_update(
        index_elements=[content_provenance.c.content_kind, content_provenance.c.content_id],
        set_={
            key: statement.excluded[key]
            for key in values
            if key not in {"content_kind", "content_id"}
        },
    ).returning(content_provenance.c.id)

    provenance_id = (await session.execute(upsert)).scalar_one()

    await session.execute(
        delete(content_source_spans).where(
            content_source_spans.c.provenance_id == provenance_id,
        )
    )
    if provenance.source_spans:
        await session.execute(
            insert(content_source_spans),
            [
                {
                    "provenance_id": provenance_id,
                    "content_item_id": span.content_item_id,
                    "start_char": span.start_char,
                    "end_char": span.end_char,
                    "start_ms": span.start_ms,
                    "end_ms": span.end_ms,
                    "excerpt": span.excerpt,
                }
                for span in provenance.source_spans
            ],
        )


async def get_provenance_map(
    session: AsyncSession,
    content_kind: ContentKind,
    content_ids: Iterable[str],
) -> dict[str, ContentProvenance]:
    """Load provenance for many content items, keyed by content id."""
    ids = list(dict.fromkeys(content_ids))
    if not ids:
        return {}

    rows = (
        await session.execute(
            select(content_provenance).where(
                content_provenance.c.content_kind == content_kind.value,
                content_provenance.c.content_id.in_(ids),
            )
        )
    ).all()
    spans = await _source_spans_by_provenance(session, [row.id for row in rows])
    return {row.content_id: _row_to_provenance(row, spans.get(row.id, ())) for row in rows}


async def unverified_provenance(
    session: AsyncSession,
    course_id: int,
) -> list[ContentProvenance]:
    """Load model-generated content for a learning path that nobody has checked."""
    rows = (
        await session.execute(
            select(content_provenance)
            .where(
                content_provenance.c.course_id == course_id,
                content_provenance.c.generated_by == ProvenanceAgent.MODEL.value,
                content_provenance.c.verified_by.is_(None),
            )
            .order_by(content_provenance.c.generated_at.desc())
        )
    ).all()
    spans = await _source_spans_by_provenance(session, [row.id for row in rows])
    return [_row_to_provenance(row, spans.get(row.id, ())) for row in rows]


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
    row: Row[tuple[object, ...]], spans: tuple[SourceSpan, ...]
) -> ContentProvenance:
    return ContentProvenance(
        content_kind=ContentKind(row.content_kind),
        content_id=row.content_id,
        course_id=row.course_id,
        origin=StoredContentOrigin(row.content_origin),
        generated_by=ProvenanceAgent(row.generated_by),
        generator_ref=row.generator_ref,
        generated_at=_as_text(row.generated_at),
        verified_by=row.verified_by,
        verified_at=_as_text(row.verified_at) or None,
        source_spans=spans,
    )


async def _source_spans_by_provenance(
    session: AsyncSession,
    provenance_ids: Sequence[int],
) -> dict[int, tuple[SourceSpan, ...]]:
    if not provenance_ids:
        return {}

    rows = (
        await session.execute(
            select(content_source_spans)
            .where(content_source_spans.c.provenance_id.in_(provenance_ids))
            .order_by(content_source_spans.c.id)
        )
    ).all()
    grouped: dict[int, list[SourceSpan]] = {}
    for row in rows:
        grouped.setdefault(row.provenance_id, []).append(
            SourceSpan(
                content_item_id=row.content_item_id,
                start_char=row.start_char,
                end_char=row.end_char,
                start_ms=row.start_ms,
                end_ms=row.end_ms,
                excerpt=row.excerpt,
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _as_timestamp(value: str | None) -> datetime | None:
    """Parse the ISO strings the domain models carry into real timestamps."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace(" ", "T", 1))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _as_text(value: datetime | None) -> str:
    return "" if value is None else value.astimezone(UTC).isoformat()


def _now() -> str:
    return datetime.now(UTC).isoformat()
