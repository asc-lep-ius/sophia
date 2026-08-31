"""Tests for the Hermes lecture download orchestration service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from sophia.domain.errors import LectureDownloadError
from sophia.domain.models import DownloadProgressEvent, Lecture, LectureTrack
from sophia.services.hermes_download import download_lectures

from .._sql import exec_sql

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


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


def _make_container(
    db: AsyncSession,
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


async def test_download_lectures_happy_path(tmp_path: Path, db: AsyncSession) -> None:
    lectures = [
        _make_lecture(episode_id="ep-001", title="Lecture 1"),
        _make_lecture(episode_id="ep-002", title="Lecture 2"),
    ]
    container = _make_container(db, tmp_path, episodes=lectures)

    results = await download_lectures(container, db, module_id=42)

    assert len(results) == 2
    assert all(r.status == "completed" for r in results)
    assert all(r.file_path is not None for r in results)
    assert all(r.error is None for r in results)


# ------------------------------------------------------------------
# Idempotency — skip already-completed
# ------------------------------------------------------------------


async def test_download_lectures_skips_completed(tmp_path: Path, db: AsyncSession) -> None:
    # Pre-insert a completed row for ep-001
    await exec_sql(
        db,
        """INSERT INTO lecture_downloads
           (episode_id, module_id, series_id, title, track_url, track_mimetype, status)
           VALUES (?, ?, ?, ?, ?, ?, 'completed')""",
        ("ep-001", 42, "series-abc", "Lecture 1", "https://x/v.mp4", "video/mp4"),
    )

    lectures = [
        _make_lecture(episode_id="ep-001", title="Lecture 1"),
        _make_lecture(episode_id="ep-002", title="Lecture 2"),
    ]
    container = _make_container(db, tmp_path, episodes=lectures)

    results = await download_lectures(container, db, module_id=42)

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


async def test_download_lectures_handles_no_tracks(tmp_path: Path, db: AsyncSession) -> None:
    lecture = _make_lecture(episode_id="ep-001", tracks=[])
    container = _make_container(db, tmp_path, episodes=[lecture])

    results = await download_lectures(container, db, module_id=42)

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].error is not None


# ------------------------------------------------------------------
# Download error handling
# ------------------------------------------------------------------


async def test_download_lectures_handles_download_error(tmp_path: Path, db: AsyncSession) -> None:
    container = _make_container(db, tmp_path)

    async def _failing_gen(*_: object, **__: object):
        raise LectureDownloadError("network timeout")
        yield  # noqa: RUF027 — makes this an async generator

    container.lecture_downloader.download_track = MagicMock(side_effect=_failing_gen)

    results = await download_lectures(container, db, module_id=42)

    assert len(results) == 1
    assert results[0].status == "failed"
    assert "network timeout" in (results[0].error or "")


async def test_a_retry_does_not_inherit_the_previous_attempts_result(
    db: AsyncSession,
) -> None:
    """A re-download clears the last run's outcome, as INSERT OR REPLACE did.

    Otherwise a failed retry renders as status='failed' beside the file_path and
    completed_at of the run before it.
    """
    from sophia.services.hermes_download import _upsert_downloading

    await exec_sql(
        db,
        "INSERT INTO lecture_downloads (episode_id, module_id, title, track_url,"
        " track_mimetype, status, file_path, file_size_bytes, error, completed_at,"
        " skip_reason, lecture_number)"
        " VALUES ('ep-1', 42, 'L1', 'u', 'audio/m4a', 'completed', '/old.m4a', 999,"
        " 'boom', '2026-01-01T00:00:00+00:00', 'silent_recording', 3)",
    )

    await _upsert_downloading(db, "ep-1", 42, "s-1", "L1", "u2", "audio/m4a")

    row = (await exec_sql(db, "SELECT * FROM lecture_downloads WHERE episode_id = 'ep-1'")).one()
    assert row.status == "downloading"
    assert row.file_path is None
    assert row.file_size_bytes is None
    assert row.error is None
    assert row.completed_at is None
    assert row.skip_reason is None
    # Catalogue metadata describes the lecture, not the attempt, so it survives.
    assert row.lecture_number == 3
