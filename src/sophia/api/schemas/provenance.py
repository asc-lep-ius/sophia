"""Provenance transport schemas shared by every generated-content response."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class ContentOrigin(StrEnum):
    """Kind of system a piece of content was ingested from.

    Reserved discriminator. Values name the *kind* of upstream system rather
    than the vendor, so the generated client never learns which product a
    deployment happens to ingest from. Adding a value is additive: the column
    behind it is free-form text, so a new origin needs no schema migration and
    breaks no existing client.
    """

    LMS = "lms"


class ProvenanceAgent(StrEnum):
    """Who produced a piece of content."""

    LEARNER = "learner"
    MODEL = "model"


class SourceSpan(ApiModel):
    """A located region of ingested material backing a piece of content.

    Character offsets locate text material and millisecond offsets locate
    time-based material; both are optional because a span may be known only as
    a whole content item.
    """

    content_item_id: str
    start_char: int | None = None
    end_char: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    excerpt: str | None = None


class Provenance(ApiModel):
    """Where a piece of content came from and whether a human has checked it.

    ``verified_by`` is null for anything no human has signed off on, which is
    what makes unverified generated content distinguishable at a glance.
    """

    origin: ContentOrigin
    generated_by: ProvenanceAgent
    generator_ref: str | None = None
    generated_at: str
    verified_by: str | None = None
    verified_at: str | None = None
    source_spans: list[SourceSpan] = Field(default_factory=list[SourceSpan])
