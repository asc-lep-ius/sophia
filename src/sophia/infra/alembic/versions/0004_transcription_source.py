"""Transcripts from published captions — source, title, and no download behind them.

``transcriptions`` gains ``source`` (``captions`` or ``whisper``), so a row
records where its text came from and ``sophia lectures status`` can show it;
``title`` and ``caption_url``, because a caption transcript is the only record
of its episode; and loses its foreign key to ``lecture_downloads``, because a
lecture whose captions were read is never downloaded and must not carry a fake
download row to satisfy one. Existing rows are Whisper's, which the default
says. See issue #156 and docs/captions-as-transcript.md.

The downgrade has to restore that foreign key, and rows without a download
cannot satisfy it, so it deletes caption-sourced transcriptions together with
their segments and index entries before re-adding the constraint. That is the
cost of the one-way door being opened here, written down rather than hidden.

Revision ID: 0004_transcription_source
Revises: 0003_study_session_scoring
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_transcription_source"
down_revision: str | None = "0003_study_session_scoring"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "transcriptions",
        sa.Column("source", sa.Text(), server_default="whisper", nullable=False),
    )
    op.add_column(
        "transcriptions",
        sa.Column("title", sa.Text(), server_default="", nullable=False),
    )
    op.add_column("transcriptions", sa.Column("caption_url", sa.Text(), nullable=True))
    op.create_check_constraint(
        "source_allowed",
        "transcriptions",
        "source IN ('captions', 'whisper')",
    )
    op.drop_constraint(
        op.f("fk_transcriptions_episode_id_lecture_downloads"),
        "transcriptions",
        type_="foreignkey",
    )


def downgrade() -> None:
    orphaned = (
        "SELECT episode_id FROM transcriptions WHERE episode_id NOT IN "
        "(SELECT episode_id FROM lecture_downloads)"
    )
    op.execute(f"DELETE FROM knowledge_index WHERE episode_id IN ({orphaned})")
    op.execute(f"DELETE FROM transcript_segments WHERE episode_id IN ({orphaned})")
    op.execute(f"DELETE FROM transcriptions WHERE episode_id IN ({orphaned})")

    op.create_foreign_key(
        op.f("fk_transcriptions_episode_id_lecture_downloads"),
        "transcriptions",
        "lecture_downloads",
        ["episode_id"],
        ["episode_id"],
    )
    op.drop_constraint(op.f("ck_transcriptions_source_allowed"), "transcriptions", type_="check")
    op.drop_column("transcriptions", "caption_url")
    op.drop_column("transcriptions", "title")
    op.drop_column("transcriptions", "source")
