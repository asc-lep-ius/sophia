"""Tests for the Hermes lecture download orchestration service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import aiosqlite

from sophia.domain.errors import LectureDownloadError
from sophia.domain.models import DownloadProgressEvent, Lecture, LectureTrack
from sophia.services.hermes_download import download_lectures

if TYPE_CHECKING:
    from pathlib import Path


def _make_lecture(
    episode_id: str = "ep-001",
    title: str = "Lecture 1",
    series_id: str = "series-abc",
    tracks: list[LectureTrack] | None = None,
) -> Lecture:
    return Lecture(
        episode_id=episode_id,
        title=title,
        series_id=series_id,
        tracks=tracks
        if tracks is not None
        else [
            LectureTrack(
                flavor="presenter/mp4",
                url="https://example.com/v.mp4",
                mimetype="video/mp4",
                resolution="1280x720",
            ),
        ],
    )


async def _progress_gen(*_: object, **__: object):
    """Fake async generator yielding one progress event."""
    yield DownloadProgressEvent(bytes_downloaded=1024, total_bytes=1024, speed_bps=512.0)


async def _setup_db(db: aiosqlite.Connection) -> None:
    """Apply the lecture_downloads schema to an in-memory DB."""
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
        INSERT OR IGNORE INTO schema_version (version) VALUES (3);

        CREATE TABLE IF NOT EXISTS lecture_downloads (
            episode_id TEXT PRIMARY KEY,
            module_id INTEGER NOT NULL,
            series_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            track_url TEXT NOT NULL,
            track_mimetype TEXT NOT NULL,
            file_path TEXT,
            file_size_bytes INTEGER,
            status TEXT NOT NULL DEFAULT 'queued',
            error TEXT,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await db.commit()


def _make_container(
    db: aiosqlite.Connection,
    tmp_path: Path,
    episodes: list[Lecture] | None = None,
    details: dict[str, Lecture | None] | None = None,
) -> MagicMock:
    """Build a mock AppContainer with wired opencast + downloader mocks."""
    ep_list = episodes if episodes is not None else [_make_lecture()]
    detail_map = details if details is not None else {ep.episode_id: ep for ep in ep_list}

    container = MagicMock()
    container.db = db
    container.settings.data_dir = tmp_path

    container.opencast.get_series_episodes = AsyncMock(return_value=ep_list)
    container.opencast.get_episode_detail = AsyncMock(
        side_effect=lambda _mid, eid: detail_map.get(eid)  # type: ignore[arg-type]
    )

    container.lecture_downloader.download_track = MagicMock(side_effect=_progress_gen)

    return container


# ------------------------------------------------------------------
# Happy path
# ------------------------------------------------------------------


async def test_download_lectures_happy_path(tmp_path: Path) -> None:
    lectures = [
        _make_lecture(episode_id="ep-001", title="Lecture 1"),
        _make_lecture(episode_id="ep-002", title="Lecture 2"),
    ]
    async with aiosqlite.connect(":memory:") as db:
        await _setup_db(db)
        container = _make_container(db, tmp_path, episodes=lectures)

        results = await download_lectures(container, module_id=42)

    assert len(results) == 2
    assert all(r.status == "completed" for r in results)
    assert all(r.file_path is not None for r in results)
    assert all(r.error is None for r in results)


# ------------------------------------------------------------------
# Idempotency — skip already-completed
# ------------------------------------------------------------------


async def test_download_lectures_skips_completed(tmp_path: Path) -> None:
    async with aiosqlite.connect(":memory:") as db:
        await _setup_db(db)

        # Pre-insert a completed row for ep-001
        await db.execute(
            """INSERT INTO lecture_downloads
               (episode_id, module_id, series_id, title, track_url, track_mimetype, status)
               VALUES (?, ?, ?, ?, ?, ?, 'completed')""",
            ("ep-001", 42, "series-abc", "Lecture 1", "https://x/v.mp4", "video/mp4"),
        )
        await db.commit()

        lectures = [
            _make_lecture(episode_id="ep-001", title="Lecture 1"),
            _make_lecture(episode_id="ep-002", title="Lecture 2"),
        ]
        container = _make_container(db, tmp_path, episodes=lectures)

        results = await download_lectures(container, module_id=42)

    assert len(results) == 2
    skipped = [r for r in results if r.status == "skipped"]
    completed = [r for r in results if r.status == "completed"]
    assert len(skipped) == 1
    assert skipped[0].episode_id == "ep-001"
    assert len(completed) == 1
    assert completed[0].episode_id == "ep-002"


# ------------------------------------------------------------------
# No tracks available
# ------------------------------------------------------------------


async def test_download_lectures_handles_no_tracks(tmp_path: Path) -> None:
    lecture = _make_lecture(episode_id="ep-001", tracks=[])
    async with aiosqlite.connect(":memory:") as db:
        await _setup_db(db)
        container = _make_container(db, tmp_path, episodes=[lecture])

        results = await download_lectures(container, module_id=42)

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].error is not None


# ------------------------------------------------------------------
# Download error handling
# ------------------------------------------------------------------


async def test_download_lectures_handles_download_error(tmp_path: Path) -> None:
    async with aiosqlite.connect(":memory:") as db:
        await _setup_db(db)
        container = _make_container(db, tmp_path)

        async def _failing_gen(*_: object, **__: object):
            raise LectureDownloadError("network timeout")
            yield  # noqa: RUF027 — makes this an async generator

        container.lecture_downloader.download_track = MagicMock(side_effect=_failing_gen)

        results = await download_lectures(container, module_id=42)

    assert len(results) == 1
    assert results[0].status == "failed"
    assert "network timeout" in (results[0].error or "")
