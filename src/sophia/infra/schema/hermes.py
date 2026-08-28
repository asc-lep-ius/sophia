"""Lecture ingestion, transcription, and knowledge index tables."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP

from sophia.infra.schema._shared import metadata, org_id_column, text_course_id_column

_NOW = text("CURRENT_TIMESTAMP")

lecture_modules = Table(
    "lecture_modules",
    metadata,
    Column("module_id", Integer, primary_key=True, autoincrement=False),
    Column("course_name", Text, nullable=False, server_default=""),
    Column("course_shortname", Text, nullable=False, server_default=""),
    org_id_column(),
    text_course_id_column(),
)

lecture_downloads = Table(
    "lecture_downloads",
    metadata,
    Column("episode_id", Text, primary_key=True),
    Column("module_id", Integer, nullable=False),
    Column("series_id", Text, nullable=False, server_default=""),
    Column("title", Text, nullable=False),
    Column("track_url", Text, nullable=False),
    Column("track_mimetype", Text, nullable=False),
    Column("file_path", Text),
    Column("file_size_bytes", Integer),
    Column("status", Text, nullable=False, server_default="queued"),
    Column("error", Text),
    Column("started_at", TIMESTAMP(timezone=True)),
    Column("completed_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("skip_reason", Text),
    Column("lecture_number", Integer),
    Column("missed_at", TIMESTAMP(timezone=True)),
    org_id_column(),
    text_course_id_column(),
    Index("idx_lecture_downloads_module", "module_id"),
    Index("idx_lecture_downloads_status", "status"),
)

transcriptions = Table(
    "transcriptions",
    metadata,
    Column(
        "episode_id",
        Text,
        ForeignKey("lecture_downloads.episode_id"),
        primary_key=True,
    ),
    Column("module_id", Integer, nullable=False),
    Column("language", Text, nullable=False, server_default="de"),
    Column("duration_s", Float()),
    Column("segment_count", Integer),
    Column("srt_path", Text),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("error", Text),
    Column("started_at", TIMESTAMP(timezone=True)),
    Column("completed_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    text_course_id_column(),
    Index("idx_transcriptions_status", "status"),
)

transcript_segments = Table(
    "transcript_segments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "episode_id",
        Text,
        ForeignKey("transcriptions.episode_id"),
        nullable=False,
    ),
    Column("segment_index", Integer, nullable=False),
    Column("start_time", Float(), nullable=False),
    Column("end_time", Float(), nullable=False),
    Column("text", Text, nullable=False),
    org_id_column(),
    text_course_id_column(),
    Index("idx_transcript_segments_episode", "episode_id"),
)

knowledge_index = Table(
    "knowledge_index",
    metadata,
    Column(
        "episode_id",
        Text,
        ForeignKey("transcriptions.episode_id"),
        primary_key=True,
    ),
    Column("module_id", Integer, nullable=False),
    Column("chunk_count", Integer, nullable=False, server_default=text("0")),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("error", Text),
    Column("indexed_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    text_course_id_column(),
    Index("idx_knowledge_index_status", "status"),
)

course_materials = Table(
    "course_materials",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("course_id", Integer, nullable=False),
    Column("module_id", Integer, nullable=False),
    Column("name", Text, nullable=False),
    Column("url", Text),
    Column("mimetype", Text),
    Column("file_size_bytes", Integer),
    Column("pdf_text", Text),
    Column("chunk_count", Integer, server_default=text("0")),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("error", Text),
    Column("created_at", Text, nullable=False, server_default=_NOW),
    org_id_column(),
    Index("uq_course_materials_url", "course_id", "url", unique=True),
)
