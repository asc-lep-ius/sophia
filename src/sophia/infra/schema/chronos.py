"""Deadline, effort estimation, and time tracking tables."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    Index,
    Integer,
    Table,
    Text,
    text,
)

from sophia.infra.schema._shared import metadata, org_id_column, text_course_id_column

# Chronos stores its timestamps as ISO-8601 text and orders them
# lexicographically. Preserved as text so that ordering keeps working.
_NOW_TEXT = text("CURRENT_TIMESTAMP")

deadline_cache = Table(
    "deadline_cache",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("course_name", Text, nullable=False, server_default=""),
    Column("deadline_type", Text, nullable=False),
    Column("due_at", Text, nullable=False),
    Column("grade_weight", Float()),
    Column("submission_status", Text),
    Column("url", Text),
    Column("extra", Text, server_default="{}"),
    Column("synced_at", Text, nullable=False, server_default=_NOW_TEXT),
    org_id_column(),
    Index("idx_deadline_cache_course", "course_id"),
    Index("idx_deadline_cache_due", "due_at"),
)

effort_estimates = Table(
    "effort_estimates",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("deadline_id", Text, nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("predicted_hours", Float(), nullable=False),
    Column("breakdown", Text),
    Column("implementation_intention", Text),
    Column("scaffold_level", Text, nullable=False, server_default="full"),
    Column("estimated_at", Text, nullable=False, server_default=_NOW_TEXT),
    org_id_column(),
    CheckConstraint("predicted_hours > 0", name="predicted_hours_positive"),
    Index("idx_effort_estimates_course", "course_id"),
    Index("idx_effort_estimates_deadline", "deadline_id"),
)

time_entries = Table(
    "time_entries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("deadline_id", Text, nullable=False),
    Column("hours", Float(), nullable=False),
    Column("source", Text, nullable=False, server_default="manual"),
    Column("note", Text),
    Column("recorded_at", Text, nullable=False, server_default=_NOW_TEXT),
    org_id_column(),
    text_course_id_column(),
    CheckConstraint("hours > 0", name="hours_positive"),
    Index("idx_time_entries_deadline", "deadline_id"),
)

active_timers = Table(
    "active_timers",
    metadata,
    Column("deadline_id", Text, primary_key=True),
    Column("started_at", Text, nullable=False),
    org_id_column(),
    text_course_id_column(),
)

deadline_reflections = Table(
    "deadline_reflections",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("deadline_id", Text, nullable=False),
    Column("predicted_hours", Float()),
    Column("actual_hours", Float()),
    Column("reflection_text", Text),
    Column("reflected_at", Text, nullable=False, server_default=_NOW_TEXT),
    org_id_column(),
    text_course_id_column(),
)
