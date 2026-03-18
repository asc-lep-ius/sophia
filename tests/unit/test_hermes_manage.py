"""Tests for hermes_manage service — discard, restore, pipeline status."""

from __future__ import annotations

import aiosqlite
import pytest

from sophia.domain.models import DownloadStatus
from sophia.infra.persistence import run_migrations


@pytest.fixture
async def db():
    db_conn = await aiosqlite.connect(":memory:")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db_conn)
    yield db_conn
    await db_conn.close()


async def _insert_download(
    db: aiosqlite.Connection,
    episode_id: str,
    module_id: int,
    *,
    title: str = "Lecture 1",
    status: str = "completed",
    skip_reason: str | None = None,
) -> None:
    await db.execute(
        """INSERT INTO lecture_downloads
           (episode_id, module_id, title, track_url, track_mimetype, status, skip_reason)
           VALUES (?, ?, ?, '', '', ?, ?)""",
        (episode_id, module_id, title, status, skip_reason),
    )
    await db.commit()


async def _insert_transcription(
    db: aiosqlite.Connection,
    episode_id: str,
    module_id: int,
    *,
    status: str = "completed",
) -> None:
    await db.execute(
        "INSERT INTO transcriptions (episode_id, module_id, status) VALUES (?, ?, ?)",
        (episode_id, module_id, status),
    )
    await db.commit()


async def _insert_index(
    db: aiosqlite.Connection,
    episode_id: str,
    module_id: int,
    *,
    status: str = "completed",
) -> None:
    await db.execute(
        "INSERT INTO knowledge_index (episode_id, module_id, status) VALUES (?, ?, ?)",
        (episode_id, module_id, status),
    )
    await db.commit()


async def _insert_segments(
    db: aiosqlite.Connection,
    episode_id: str,
    count: int = 3,
) -> None:
    for i in range(count):
        await db.execute(
            """INSERT INTO transcript_segments
               (episode_id, segment_index, start_time, end_time, text)
               VALUES (?, ?, ?, ?, ?)""",
            (episode_id, i, i * 5.0, (i + 1) * 5.0, f"Segment {i}"),
        )
    await db.commit()


# ------------------------------------------------------------------
# discard_episode
# ------------------------------------------------------------------


class TestDiscardEpisode:
    async def test_discards_completed_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import discard_episode

        await _insert_download(db, "ep-1", 100, status="completed")
        result = await discard_episode(db, 100, "ep-1")

        assert result is True
        row = await (
            await db.execute("SELECT status FROM lecture_downloads WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row[0] == DownloadStatus.DISCARDED

    async def test_discards_skipped_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import discard_episode

        await _insert_download(db, "ep-2", 100, status="skipped")
        result = await discard_episode(db, 100, "ep-2")

        assert result is True
        row = await (
            await db.execute("SELECT status FROM lecture_downloads WHERE episode_id = 'ep-2'")
        ).fetchone()
        assert row[0] == DownloadStatus.DISCARDED

    async def test_discards_failed_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import discard_episode

        await _insert_download(db, "ep-3", 100, status="failed")
        result = await discard_episode(db, 100, "ep-3")

        assert result is True
        row = await (
            await db.execute("SELECT status FROM lecture_downloads WHERE episode_id = 'ep-3'")
        ).fetchone()
        assert row[0] == DownloadStatus.DISCARDED

    async def test_returns_false_for_nonexistent_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import discard_episode

        result = await discard_episode(db, 100, "no-such-ep")
        assert result is False

    async def test_returns_false_for_wrong_module(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import discard_episode

        await _insert_download(db, "ep-1", 100, status="completed")
        result = await discard_episode(db, 999, "ep-1")
        assert result is False


# ------------------------------------------------------------------
# restore_episode
# ------------------------------------------------------------------


class TestRestoreEpisode:
    async def test_restores_discarded_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import restore_episode

        await _insert_download(db, "ep-1", 100, status="discarded")
        result = await restore_episode(db, 100, "ep-1")

        assert result is True
        row = await (
            await db.execute("SELECT status FROM lecture_downloads WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row[0] == DownloadStatus.QUEUED

    async def test_returns_false_for_non_discarded_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import restore_episode

        await _insert_download(db, "ep-1", 100, status="completed")
        result = await restore_episode(db, 100, "ep-1")
        assert result is False

    async def test_returns_false_for_nonexistent_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import restore_episode

        result = await restore_episode(db, 100, "no-such-ep")
        assert result is False


# ------------------------------------------------------------------
# get_pipeline_status
# ------------------------------------------------------------------


class TestGetPipelineStatus:
    async def test_download_only(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_pipeline_status

        await _insert_download(db, "ep-1", 100, title="Intro")
        statuses = await get_pipeline_status(db, 100)

        assert len(statuses) == 1
        ep = statuses[0]
        assert ep.episode_id == "ep-1"
        assert ep.title == "Intro"
        assert ep.download_status == "completed"
        assert ep.transcription_status is None
        assert ep.index_status is None
        assert ep.skip_reason is None

    async def test_fully_indexed(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_pipeline_status

        await _insert_download(db, "ep-1", 100, title="Full Pipeline")
        await _insert_transcription(db, "ep-1", 100)
        await _insert_index(db, "ep-1", 100)

        statuses = await get_pipeline_status(db, 100)
        assert len(statuses) == 1
        ep = statuses[0]
        assert ep.download_status == "completed"
        assert ep.transcription_status == "completed"
        assert ep.index_status == "completed"

    async def test_skipped_with_reason(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_pipeline_status

        await _insert_download(
            db, "ep-1", 100, title="Silent", status="skipped", skip_reason="silence>80%"
        )
        statuses = await get_pipeline_status(db, 100)

        assert len(statuses) == 1
        assert statuses[0].download_status == "skipped"
        assert statuses[0].skip_reason == "silence>80%"

    async def test_multiple_episodes(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_pipeline_status

        await _insert_download(db, "ep-1", 100, title="A")
        await _insert_download(db, "ep-2", 100, title="B", status="failed")
        await _insert_download(db, "ep-3", 200, title="C")

        statuses = await get_pipeline_status(db, 100)
        assert len(statuses) == 2
        ids = {s.episode_id for s in statuses}
        assert ids == {"ep-1", "ep-2"}

    async def test_empty_module(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_pipeline_status

        statuses = await get_pipeline_status(db, 999)
        assert statuses == []

    async def test_discarded_episode_shown(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_pipeline_status

        await _insert_download(db, "ep-1", 100, title="Gone", status="discarded")
        statuses = await get_pipeline_status(db, 100)

        assert len(statuses) == 1
        assert statuses[0].download_status == "discarded"


# ------------------------------------------------------------------
# purge_episode
# ------------------------------------------------------------------


class _FakeStore:
    """Minimal KnowledgeStore that tracks delete_episode calls."""

    def __init__(self, chunks_by_episode: dict[str, int] | None = None) -> None:
        self._chunks = chunks_by_episode or {}
        self.deleted: list[str] = []

    def delete_episode(self, episode_id: str) -> int:
        self.deleted.append(episode_id)
        return self._chunks.get(episode_id, 0)


class TestPurgeEpisode:
    async def test_purge_fully_indexed_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import purge_episode

        await _insert_download(db, "ep-1", 100, title="Full")
        await _insert_transcription(db, "ep-1", 100)
        await _insert_segments(db, "ep-1", count=5)
        await _insert_index(db, "ep-1", 100)

        store = _FakeStore({"ep-1": 3})
        result = await purge_episode(db, store, 100, "ep-1")

        assert result.knowledge_chunks == 3
        assert result.transcript_segments == 5
        assert result.transcriptions == 1
        assert result.knowledge_index == 1
        assert store.deleted == ["ep-1"]

        # Download record preserved
        row = await (
            await db.execute("SELECT status FROM lecture_downloads WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row is not None

        # Transcription data removed
        row = await (
            await db.execute("SELECT COUNT(*) FROM transcript_segments WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row[0] == 0

        row = await (
            await db.execute("SELECT COUNT(*) FROM transcriptions WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row[0] == 0

        row = await (
            await db.execute("SELECT COUNT(*) FROM knowledge_index WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row[0] == 0

    async def test_purge_nonexistent_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import purge_episode

        store = _FakeStore()
        result = await purge_episode(db, store, 100, "no-such-ep")

        assert result.knowledge_chunks == 0
        assert result.transcript_segments == 0
        assert result.transcriptions == 0
        assert result.knowledge_index == 0
        assert store.deleted == []

    async def test_purge_download_only_episode(self, db: aiosqlite.Connection) -> None:
        """Episode with download record but no transcription or index."""
        from sophia.services.hermes_manage import purge_episode

        await _insert_download(db, "ep-1", 100, title="Download Only")

        store = _FakeStore()
        result = await purge_episode(db, store, 100, "ep-1")

        assert result.knowledge_chunks == 0
        assert result.transcript_segments == 0
        assert result.transcriptions == 0
        assert result.knowledge_index == 0

        # Download record still present
        row = await (
            await db.execute("SELECT COUNT(*) FROM lecture_downloads WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row[0] == 1

    async def test_purge_wrong_module_id_returns_zeros(self, db: aiosqlite.Connection) -> None:
        """Purge with a module_id that doesn't own the episode does nothing."""
        from sophia.services.hermes_manage import purge_episode

        await _insert_download(db, "ep-1", 100, title="Owned by 100")
        await _insert_transcription(db, "ep-1", 100)
        await _insert_segments(db, "ep-1", count=3)
        await _insert_index(db, "ep-1", 100)

        store = _FakeStore({"ep-1": 2})
        result = await purge_episode(db, store, 999, "ep-1")

        assert result.knowledge_chunks == 0
        assert result.transcript_segments == 0
        assert result.transcriptions == 0
        assert result.knowledge_index == 0
        assert store.deleted == []

        # All data for module 100 untouched
        row = await (
            await db.execute("SELECT COUNT(*) FROM transcript_segments WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row[0] == 3

    async def test_purge_scoped_to_module(self, db: aiosqlite.Connection) -> None:
        """Purging module 100's episode doesn't affect module 200's data."""
        from sophia.services.hermes_manage import purge_episode

        await _insert_download(db, "ep-1", 100, title="Mod100")
        await _insert_transcription(db, "ep-1", 100)
        await _insert_segments(db, "ep-1", count=2)
        await _insert_index(db, "ep-1", 100)

        await _insert_download(db, "ep-2", 200, title="Mod200")
        await _insert_transcription(db, "ep-2", 200)
        await _insert_segments(db, "ep-2", count=4)
        await _insert_index(db, "ep-2", 200)

        store = _FakeStore({"ep-1": 1})
        result = await purge_episode(db, store, 100, "ep-1")

        assert result.transcriptions == 1
        assert result.knowledge_index == 1

        # Module 200's records untouched
        row = await (
            await db.execute(
                "SELECT COUNT(*) FROM transcriptions WHERE episode_id = 'ep-2' AND module_id = 200"
            )
        ).fetchone()
        assert row[0] == 1

        row = await (
            await db.execute(
                "SELECT COUNT(*) FROM knowledge_index WHERE episode_id = 'ep-2' AND module_id = 200"
            )
        ).fetchone()
        assert row[0] == 1

        row = await (
            await db.execute("SELECT COUNT(*) FROM transcript_segments WHERE episode_id = 'ep-2'")
        ).fetchone()
        assert row[0] == 4
