"""Tests for hermes_manage service — discard, restore, pipeline status, lecture numbering."""

from __future__ import annotations

from typing import Any

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
        assert row is not None
        assert row[0] == DownloadStatus.DISCARDED

    async def test_discards_skipped_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import discard_episode

        await _insert_download(db, "ep-2", 100, status="skipped")
        result = await discard_episode(db, 100, "ep-2")

        assert result is True
        row = await (
            await db.execute("SELECT status FROM lecture_downloads WHERE episode_id = 'ep-2'")
        ).fetchone()
        assert row is not None
        assert row[0] == DownloadStatus.DISCARDED

    async def test_discards_failed_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import discard_episode

        await _insert_download(db, "ep-3", 100, status="failed")
        result = await discard_episode(db, 100, "ep-3")

        assert result is True
        row = await (
            await db.execute("SELECT status FROM lecture_downloads WHERE episode_id = 'ep-3'")
        ).fetchone()
        assert row is not None
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
        assert row is not None
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
# mark_missed / unmark_missed / get_missed_episodes
# ------------------------------------------------------------------


class TestMarkMissed:
    async def test_marks_episode_as_missed(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import mark_missed

        await _insert_download(db, "ep-1", 100, status="completed")
        result = await mark_missed(db, 100, "ep-1")
        assert result is True
        row = await (
            await db.execute("SELECT missed_at FROM lecture_downloads WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row[0] is not None

    async def test_already_missed_returns_false(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import mark_missed

        await _insert_download(db, "ep-1", 100, status="completed")
        await mark_missed(db, 100, "ep-1")
        result = await mark_missed(db, 100, "ep-1")
        assert result is False

    async def test_nonexistent_episode_returns_false(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import mark_missed

        result = await mark_missed(db, 100, "no-such-ep")
        assert result is False

    async def test_wrong_module_returns_false(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import mark_missed

        await _insert_download(db, "ep-1", 100, status="completed")
        result = await mark_missed(db, 999, "ep-1")
        assert result is False


class TestUnmarkMissed:
    async def test_unmarks_missed_episode(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import mark_missed, unmark_missed

        await _insert_download(db, "ep-1", 100, status="completed")
        await mark_missed(db, 100, "ep-1")
        result = await unmark_missed(db, 100, "ep-1")
        assert result is True
        row = await (
            await db.execute("SELECT missed_at FROM lecture_downloads WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row[0] is None

    async def test_not_missed_returns_false(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import unmark_missed

        await _insert_download(db, "ep-1", 100, status="completed")
        result = await unmark_missed(db, 100, "ep-1")
        assert result is False

    async def test_nonexistent_returns_false(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import unmark_missed

        result = await unmark_missed(db, 100, "no-such-ep")
        assert result is False


class TestGetMissedEpisodes:
    async def test_returns_only_missed(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_missed_episodes, mark_missed

        await _insert_download(db, "ep-1", 100, title="Lecture 1", status="completed")
        await _insert_download(db, "ep-2", 100, title="Lecture 2", status="completed")
        await _insert_download(db, "ep-3", 100, title="Lecture 3", status="completed")
        await mark_missed(db, 100, "ep-1")
        await mark_missed(db, 100, "ep-3")
        missed = await get_missed_episodes(db, 100)
        assert len(missed) == 2
        ids = {ep.episode_id for ep in missed}
        assert ids == {"ep-1", "ep-3"}

    async def test_empty_when_none_missed(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_missed_episodes

        await _insert_download(db, "ep-1", 100, status="completed")
        missed = await get_missed_episodes(db, 100)
        assert missed == []

    async def test_missed_at_populated(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_missed_episodes, mark_missed

        await _insert_download(db, "ep-1", 100, status="completed")
        await mark_missed(db, 100, "ep-1")
        missed = await get_missed_episodes(db, 100)
        assert len(missed) == 1
        assert missed[0].missed_at is not None


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

    async def test_missed_at_reflected_in_status(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_pipeline_status, mark_missed

        await _insert_download(db, "ep-1", 100, title="Missed Lecture", status="completed")
        await mark_missed(db, 100, "ep-1")
        statuses = await get_pipeline_status(db, 100)
        assert len(statuses) == 1
        assert statuses[0].missed_at is not None


# ------------------------------------------------------------------
# purge_episode
# ------------------------------------------------------------------


class _FakeStore:
    """Minimal KnowledgeStore that tracks delete_episode calls."""

    def __init__(self, chunks_by_episode: dict[str, int] | None = None) -> None:
        self._chunks = chunks_by_episode or {}
        self.deleted: list[str] = []

    def add_chunks(self, chunks: list[Any], embeddings: list[list[float]]) -> None:  # noqa: ARG002
        pass

    def search(
        self,
        query_embedding: list[float],  # noqa: ARG002
        *,
        n_results: int = 5,  # noqa: ARG002
        episode_ids: list[str] | None = None,  # noqa: ARG002
    ) -> list[Any]:
        return []

    def has_episode(self, episode_id: str) -> bool:  # noqa: ARG002
        return False

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
        assert row is not None
        assert row[0] == 0

        row = await (
            await db.execute("SELECT COUNT(*) FROM transcriptions WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row is not None
        assert row[0] == 0

        row = await (
            await db.execute("SELECT COUNT(*) FROM knowledge_index WHERE episode_id = 'ep-1'")
        ).fetchone()
        assert row is not None
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
        assert row is not None
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
        assert row is not None
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
        assert row is not None
        assert row[0] == 1

        row = await (
            await db.execute(
                "SELECT COUNT(*) FROM knowledge_index WHERE episode_id = 'ep-2' AND module_id = 200"
            )
        ).fetchone()
        assert row is not None
        assert row[0] == 1

        row = await (
            await db.execute("SELECT COUNT(*) FROM transcript_segments WHERE episode_id = 'ep-2'")
        ).fetchone()
        assert row is not None
        assert row[0] == 4


# ------------------------------------------------------------------
# infer_lecture_number
# ------------------------------------------------------------------


class TestInferLectureNumber:
    def test_english_title(self) -> None:
        from sophia.services.hermes_manage import infer_lecture_number

        assert infer_lecture_number("Lecture 3: Sorting") == 3

    def test_german_title(self) -> None:
        from sophia.services.hermes_manage import infer_lecture_number

        assert infer_lecture_number("Vorlesung 7: Analysis") == 7

    def test_hash_prefix(self) -> None:
        from sophia.services.hermes_manage import infer_lecture_number

        assert infer_lecture_number("#5 Fourier") == 5

    def test_no_number_returns_none(self) -> None:
        from sophia.services.hermes_manage import infer_lecture_number

        assert infer_lecture_number("Introduction to Algorithms") is None

    def test_vo_abbreviation(self) -> None:
        from sophia.services.hermes_manage import infer_lecture_number

        assert infer_lecture_number("VO 12 Logik") == 12

    def test_lva_abbreviation(self) -> None:
        from sophia.services.hermes_manage import infer_lecture_number

        assert infer_lecture_number("LVA 2: Grundlagen") == 2


# ------------------------------------------------------------------
# assign_lecture_numbers
# ------------------------------------------------------------------


class TestAssignLectureNumbers:
    async def test_mixed_parseable_and_unparseable(self, db: aiosqlite.Connection) -> None:
        """Episodes with parseable titles get those numbers; gaps filled by order."""
        from sophia.services.hermes_manage import assign_lecture_numbers

        # Insert in creation order (created_at varies)
        await db.execute(
            "INSERT INTO lecture_downloads "
            "(episode_id, module_id, title, track_url, track_mimetype, status, created_at) "
            "VALUES (?, ?, ?, '', '', 'completed', ?)",
            ("ep-a", 100, "Introduction", "2025-01-01 09:00:00"),
        )
        await db.execute(
            "INSERT INTO lecture_downloads "
            "(episode_id, module_id, title, track_url, track_mimetype, status, created_at) "
            "VALUES (?, ?, ?, '', '', 'completed', ?)",
            ("ep-b", 100, "Lecture 3: Trees", "2025-01-02 09:00:00"),
        )
        await db.execute(
            "INSERT INTO lecture_downloads "
            "(episode_id, module_id, title, track_url, track_mimetype, status, created_at) "
            "VALUES (?, ?, ?, '', '', 'completed', ?)",
            ("ep-c", 100, "Sorting overview", "2025-01-03 09:00:00"),
        )
        await db.commit()

        await assign_lecture_numbers(db, 100)

        cursor = await db.execute(
            "SELECT episode_id, lecture_number FROM lecture_downloads "
            "WHERE module_id = 100 ORDER BY lecture_number"
        )
        rows = await cursor.fetchall()
        numbers = {row[0]: row[1] for row in rows}

        # "Lecture 3: Trees" → 3
        assert numbers["ep-b"] == 3
        # The other two get sequential numbers skipping 3: 1, 2
        assert numbers["ep-a"] == 1
        assert numbers["ep-c"] == 2

    async def test_all_parseable(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import assign_lecture_numbers

        await db.execute(
            "INSERT INTO lecture_downloads "
            "(episode_id, module_id, title, track_url, track_mimetype, status, created_at) "
            "VALUES (?, ?, ?, '', '', 'completed', ?)",
            ("ep-1", 100, "Lecture 2: B", "2025-01-01 09:00:00"),
        )
        await db.execute(
            "INSERT INTO lecture_downloads "
            "(episode_id, module_id, title, track_url, track_mimetype, status, created_at) "
            "VALUES (?, ?, ?, '', '', 'completed', ?)",
            ("ep-2", 100, "Lecture 1: A", "2025-01-02 09:00:00"),
        )
        await db.commit()

        await assign_lecture_numbers(db, 100)

        cursor = await db.execute(
            "SELECT episode_id, lecture_number FROM lecture_downloads WHERE module_id = 100"
        )
        rows = await cursor.fetchall()
        numbers = {row[0]: row[1] for row in rows}
        assert numbers["ep-1"] == 2
        assert numbers["ep-2"] == 1

    async def test_all_unparseable(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import assign_lecture_numbers

        await db.execute(
            "INSERT INTO lecture_downloads "
            "(episode_id, module_id, title, track_url, track_mimetype, status, created_at) "
            "VALUES (?, ?, ?, '', '', 'completed', ?)",
            ("ep-x", 100, "Overview", "2025-01-01 09:00:00"),
        )
        await db.execute(
            "INSERT INTO lecture_downloads "
            "(episode_id, module_id, title, track_url, track_mimetype, status, created_at) "
            "VALUES (?, ?, ?, '', '', 'completed', ?)",
            ("ep-y", 100, "Summary", "2025-01-02 09:00:00"),
        )
        await db.commit()

        await assign_lecture_numbers(db, 100)

        cursor = await db.execute(
            "SELECT episode_id, lecture_number FROM lecture_downloads "
            "WHERE module_id = 100 ORDER BY lecture_number"
        )
        rows = await cursor.fetchall()
        numbers = {row[0]: row[1] for row in rows}
        assert numbers["ep-x"] == 1
        assert numbers["ep-y"] == 2


# ------------------------------------------------------------------
# EpisodeStatus.lecture_number
# ------------------------------------------------------------------


class TestEpisodeStatusLectureNumber:
    async def test_field_exists_and_populated(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_pipeline_status

        await db.execute(
            "INSERT INTO lecture_downloads "
            "(episode_id, module_id, title, track_url, track_mimetype, status, lecture_number) "
            "VALUES (?, ?, ?, '', '', 'completed', ?)",
            ("ep-num", 100, "Lecture 5", 5),
        )
        await db.commit()

        statuses = await get_pipeline_status(db, 100)
        assert len(statuses) == 1
        assert statuses[0].lecture_number == 5

    async def test_field_none_when_unset(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_pipeline_status

        await _insert_download(db, "ep-no-num", 100, title="No Number")
        statuses = await get_pipeline_status(db, 100)
        assert len(statuses) == 1
        assert statuses[0].lecture_number is None


# ------------------------------------------------------------------
# purge_module
# ------------------------------------------------------------------


class TestPurgeModule:
    async def test_purge_module_purges_all_episodes(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import purge_module

        for i in range(3):
            ep = f"ep-{i}"
            await _insert_download(db, ep, 100, title=f"Lecture {i}")
            await _insert_transcription(db, ep, 100)
            await _insert_segments(db, ep, count=2)
            await _insert_index(db, ep, 100)

        store = _FakeStore({f"ep-{i}": 4 for i in range(3)})
        result = await purge_module(db, store, 100)

        assert result.knowledge_chunks == 12
        assert result.transcript_segments == 6
        assert result.transcriptions == 3
        assert result.knowledge_index == 3

        # Download records preserved
        row = await (
            await db.execute("SELECT COUNT(*) FROM lecture_downloads WHERE module_id = 100")
        ).fetchone()
        assert row is not None
        assert row[0] == 3

        # All indexed data removed
        for table in ("transcriptions", "knowledge_index"):
            row = await (
                await db.execute(f"SELECT COUNT(*) FROM {table} WHERE module_id = 100")  # noqa: S608
            ).fetchone()
            assert row is not None
            assert row[0] == 0

    async def test_purge_module_empty_module(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import purge_module

        store = _FakeStore()
        result = await purge_module(db, store, 999)

        assert result.knowledge_chunks == 0
        assert result.transcript_segments == 0
        assert result.transcriptions == 0
        assert result.knowledge_index == 0

    async def test_purge_module_accumulates_counts(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import purge_module

        await _insert_download(db, "ep-a", 100, title="A")
        await _insert_transcription(db, "ep-a", 100)
        await _insert_segments(db, "ep-a", count=3)
        await _insert_index(db, "ep-a", 100)

        await _insert_download(db, "ep-b", 100, title="B")
        await _insert_transcription(db, "ep-b", 100)
        await _insert_segments(db, "ep-b", count=5)
        await _insert_index(db, "ep-b", 100)

        store = _FakeStore({"ep-a": 2, "ep-b": 7})
        result = await purge_module(db, store, 100)

        assert result.knowledge_chunks == 2 + 7
        assert result.transcript_segments == 3 + 5
        assert result.transcriptions == 2
        assert result.knowledge_index == 2


# ------------------------------------------------------------------
# get_episode_count
# ------------------------------------------------------------------


class TestGetEpisodeCount:
    async def test_returns_count(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_episode_count

        for i in range(3):
            await _insert_download(db, f"ep-{i}", 100, title=f"Lecture {i}")

        assert await get_episode_count(db, 100) == 3

    async def test_empty_module(self, db: aiosqlite.Connection) -> None:
        from sophia.services.hermes_manage import get_episode_count

        assert await get_episode_count(db, 999) == 0
