"""Book discovery, download, and scheduling tables."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP

from sophia.infra.schema._shared import metadata, org_id_column, text_course_id_column

_NOW = text("CURRENT_TIMESTAMP")

downloads = Table(
    "downloads",
    metadata,
    Column("md5", Text, primary_key=True),
    Column("isbn", Text),
    Column("title", Text, nullable=False),
    Column("authors", Text),
    Column("format", Text, nullable=False),
    Column("size_bytes", Integer),
    Column("path", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("is_open_access", Boolean(), server_default=text("FALSE")),
    Column("retail_price", Float()),
    Column("downloaded_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    text_course_id_column(),
)

book_cache = Table(
    "book_cache",
    metadata,
    Column("isbn", Text, primary_key=True),
    Column("title", Text),
    Column("authors", Text),
    Column("metadata_json", Text),
    Column("last_searched", TIMESTAMP(timezone=True)),
    org_id_column(),
    text_course_id_column(),
)

metacognition_log = Table(
    "metacognition_log",
    metadata,
    Column("domain", Text, nullable=False),
    Column("item_id", Text, nullable=False),
    Column("predicted", Float(), nullable=False),
    Column("actual", Float()),
    Column("predicted_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("actual_at", TIMESTAMP(timezone=True)),
    org_id_column(),
    text_course_id_column(),
    PrimaryKeyConstraint("domain", "item_id"),
)

discovered_references = Table(
    "discovered_references",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("authors", Text, nullable=False, server_default="[]"),
    Column("isbn", Text),
    Column("source", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("course_name", Text, nullable=False, server_default=""),
    Column("confidence", Float(), nullable=False, server_default=text("1.0")),
    Column("discovered_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    UniqueConstraint("title", "course_id", "source", name="uq_discovered_references_title"),
    Index("idx_discovered_refs_course", "course_id"),
    Index("idx_discovered_refs_course_name", "course_name"),
    Index("idx_discovered_refs_isbn", "isbn"),
)

scheduled_jobs = Table(
    "scheduled_jobs",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column("command", Text, nullable=False),
    Column("scheduled_for", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("description", Text, nullable=False, server_default=""),
    org_id_column(),
    text_course_id_column(),
)
