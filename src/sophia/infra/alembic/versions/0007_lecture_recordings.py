"""Recordings with their dates, and the scope of a processing job.

``lecture_recordings`` holds every recording a module's series page lists,
with the date the page gives it, so Process can cover only the recordings
dated within the course's own semester and the page can say how many older
ones are still unprocessed. ``ingestion_jobs.scope`` records which of the two
a job covers: ``semester``, the default for Process, the scan and the nightly
run, or ``older`` for the one-off "Process older recordings too". See #128.

Revision ID: 0007_lecture_recordings
Revises: 0006_lecture_processing
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision: str = "0007_lecture_recordings"
down_revision: str | None = "0006_lecture_processing"
branch_labels: str | None = None
depends_on: str | None = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "lecture_recordings",
        sa.Column("episode_id", sa.Text(), primary_key=True),
        sa.Column("module_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("recorded_on", sa.Date(), nullable=True),
        sa.Column("first_seen_at", TIMESTAMP(timezone=True), server_default=_NOW),
        sa.Column("last_seen_at", TIMESTAMP(timezone=True), server_default=_NOW),
        sa.Column("org_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("course_id", sa.Text(), nullable=False, server_default="default"),
    )
    op.create_index("idx_lecture_recordings_module", "lecture_recordings", ["module_id"])

    op.add_column(
        "ingestion_jobs",
        sa.Column("scope", sa.Text(), nullable=False, server_default="semester"),
    )
    op.create_check_constraint("scope_allowed", "ingestion_jobs", "scope IN ('semester', 'older')")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_ingestion_jobs_scope_allowed"), "ingestion_jobs", type_="check")
    op.drop_column("ingestion_jobs", "scope")
    op.drop_index("idx_lecture_recordings_module", table_name="lecture_recordings")
    op.drop_table("lecture_recordings")
