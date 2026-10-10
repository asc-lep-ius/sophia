"""Lecture ingestion, transcription, and knowledge index tables."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
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

# Every recording a module's series page lists, with the date the page gives
# it, written at discovery and refreshed by the media stage. The date decides
# whether Process covers a recording: only those dated within the course's own
# semester, the rest on request (#128). A recording is "processed" once it has
# a completed transcript; this table never says so itself.
lecture_recordings = Table(
    "lecture_recordings",
    metadata,
    Column("episode_id", Text, primary_key=True),
    Column("module_id", Integer, nullable=False),
    Column("title", Text, nullable=False, server_default=""),
    Column("recorded_on", Date),
    Column("first_seen_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("last_seen_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
    text_course_id_column(),
    Index("idx_lecture_recordings_module", "module_id"),
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

# No foreign key to lecture_downloads since 0004: a transcript read from the
# player's published captions has no download behind it, so the episode's
# title and module live here as well. See docs/captions-as-transcript.md.
transcriptions = Table(
    "transcriptions",
    metadata,
    Column("episode_id", Text, primary_key=True),
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
    Column("source", Text, nullable=False, server_default="whisper"),
    Column("title", Text, nullable=False, server_default=""),
    Column("caption_url", Text),
    CheckConstraint("source IN ('captions', 'whisper')", name="source_allowed"),
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

# The queue between the API and the processing worker. The API inserts a
# queued row when a learner presses Process, a scan or the nightly run finds a
# subscribed course, and reads the row back for status; the worker claims it,
# records which stage of which module it is on, and finishes it. The partial
# unique index is the "one job per course" rule, enforced where two requests
# racing each other cannot both get past it (#128). ``scope`` says which of
# the course's recordings the job covers: ``semester`` for those dated within
# the course's own semester, ``older`` for the one-off run over the rest.
ingestion_jobs = Table(
    "ingestion_jobs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("course_id", Integer, nullable=False),
    Column("status", Text, nullable=False, server_default="queued"),
    Column("requested_by", Text, nullable=False, server_default="student"),
    Column("scope", Text, nullable=False, server_default="semester"),
    Column("stage", Text),
    Column("module_id", Integer),
    Column("error", Text),
    Column("worker_id", Text),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("started_at", TIMESTAMP(timezone=True)),
    Column("finished_at", TIMESTAMP(timezone=True)),
    org_id_column(),
    CheckConstraint(
        "status IN ('queued', 'running', 'completed', 'failed')",
        name="status_allowed",
    ),
    CheckConstraint("scope IN ('semester', 'older')", name="scope_allowed"),
    Index("idx_ingestion_jobs_course", "course_id"),
    Index(
        "uq_ingestion_jobs_active_course",
        "course_id",
        unique=True,
        postgresql_where=text("status IN ('queued', 'running')"),
    ),
)

# One row per worker process, refreshed every poll. ``capable`` and ``reason``
# are what the API shows a learner who presses Process on a box with no usable
# GPU or no Hermes install: a refusal with the reason, never a job that sits
# queued forever (#128).
ingestion_workers = Table(
    "ingestion_workers",
    metadata,
    Column("worker_id", Text, primary_key=True),
    Column("hostname", Text, nullable=False, server_default=""),
    Column("capable", Boolean(), nullable=False, server_default=text("false")),
    Column("reason", Text, nullable=False, server_default=""),
    Column("gpu_name", Text, nullable=False, server_default=""),
    Column("started_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("last_seen_at", TIMESTAMP(timezone=True), server_default=_NOW),
    org_id_column(),
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
