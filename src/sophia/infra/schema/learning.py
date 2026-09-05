"""Provenance, learning event, question, and content language tables."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

from sophia.infra.schema._shared import metadata, org_id_column

_NOW = text("CURRENT_TIMESTAMP")

learning_path_settings = Table(
    "learning_path_settings",
    metadata,
    Column("course_id", Integer, primary_key=True, autoincrement=False),
    Column("exam_language", Text, nullable=False, server_default="de"),
    Column("content_origin", Text, nullable=False, server_default="tuwel"),
    org_id_column(),
    Column("updated_at", TIMESTAMP(timezone=True), server_default=_NOW),
)

content_provenance = Table(
    "content_provenance",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("content_kind", Text, nullable=False),
    Column("content_id", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("content_origin", Text, nullable=False, server_default="tuwel"),
    Column("generated_by", Text, nullable=False),
    Column("generator_ref", Text),
    Column("generated_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("verified_by", Text),
    Column("verified_at", TIMESTAMP(timezone=True)),
    org_id_column(),
    UniqueConstraint("content_kind", "content_id", name="uq_content_provenance_content_kind"),
    Index("idx_content_provenance_scope", "course_id", "content_kind"),
)

content_source_spans = Table(
    "content_source_spans",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "provenance_id",
        Integer,
        ForeignKey("content_provenance.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("content_item_id", Text, nullable=False),
    Column("start_char", Integer),
    Column("end_char", Integer),
    Column("start_ms", Integer),
    Column("end_ms", Integer),
    Column("excerpt", Text),
    Index("idx_content_source_spans_provenance", "provenance_id"),
)

content_translations = Table(
    "content_translations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("content_kind", Text, nullable=False),
    Column("content_id", Text, nullable=False),
    Column("language", Text, nullable=False),
    Column("translated_text", Text, nullable=False, server_default=""),
    Column("course_id", Integer, nullable=False),
    org_id_column(),
    Column("translated_at", TIMESTAMP(timezone=True), server_default=_NOW),
    UniqueConstraint(
        "content_kind",
        "content_id",
        "language",
        name="uq_content_translations_content_kind",
    ),
)

generated_questions = Table(
    "generated_questions",
    metadata,
    Column("id", Text, primary_key=True),
    Column("course_id", Integer, nullable=False),
    Column("topic", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("prompt", Text, nullable=False, server_default=""),
    Column("difficulty", Text, nullable=False),
    Column("content_language", Text, nullable=False, server_default="de"),
    Column("options", Text, nullable=False, server_default="[]"),
    Column("segments", Text, nullable=False, server_default="[]"),
    Column("elaboration_policy", Text),
    org_id_column(),
    Column("created_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("session_id", Integer, ForeignKey("study_sessions.id")),
    Index("idx_generated_questions_scope", "course_id", "topic"),
    Index("idx_generated_questions_session", "session_id", "created_at"),
)

learning_events = Table(
    "learning_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("event_id", Text, nullable=False, unique=True),
    Column("course_id", Integer, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("occurred_at", TIMESTAMP(timezone=True), nullable=False),
    Column("received_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("session_id", Integer),
    Column("question_id", Text),
    Column("payload", Text, nullable=False, server_default="{}"),
    org_id_column(),
    Index("idx_learning_events_trace", "course_id", "question_id", "user_id", "event_type"),
    Index("idx_learning_events_retention", "received_at"),
)

question_attempts = Table(
    "question_attempts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("course_id", Integer, nullable=False),
    Column(
        "question_id",
        Text,
        ForeignKey("generated_questions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("user_id", Text, nullable=False),
    Column("answer_text", Text, nullable=False),
    Column("confidence", Integer),
    org_id_column(),
    Column("submitted_at", TIMESTAMP(timezone=True), server_default=_NOW),
    Column("session_id", Integer, ForeignKey("study_sessions.id")),
    Column("request_id", Text),
    Column("score", Float()),
    Column("self_rating", Integer),
    Column("phase", Text, nullable=False, server_default="practice"),
    CheckConstraint("score IS NULL OR score BETWEEN 0.0 AND 1.0", name="score_ratio"),
    CheckConstraint(
        "phase IN ('pre_test', 'practice', 'post_test')",
        name="phase_valid",
    ),
    CheckConstraint(
        "self_rating IS NULL OR self_rating BETWEEN 1 AND 4",
        name="self_rating_range",
    ),
    UniqueConstraint(
        "org_id",
        "session_id",
        "user_id",
        "request_id",
        name="uq_question_attempts_session_request",
    ),
    Index("idx_question_attempts_scope", "course_id", "question_id", "user_id"),
)

study_events = Table(
    "study_events",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("session_id", Integer, ForeignKey("study_sessions.id"), nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB(), nullable=False, server_default=text("'{}'::jsonb")),
    Column("request_id", Text),
    Column("client_time", TIMESTAMP(timezone=True)),
    Column("server_time", TIMESTAMP(timezone=True), nullable=False, server_default=_NOW),
    Column("schema_version", Integer, nullable=False, server_default=text("1")),
    org_id_column(),
    Index("idx_study_events_session", "session_id", "id"),
    Index("idx_study_events_retention", "server_time"),
)
