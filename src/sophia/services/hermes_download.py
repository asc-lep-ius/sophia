"""Hermes lecture download orchestration — discover, download, extract, persist."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from sophia.adapters.lecture_downloader import (
    detect_silence,
    ext_from_mimetype,
    extract_audio,
    select_best_track,
)
from sophia.domain.errors import LectureDownloadError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import aiosqlite

    from sophia.domain.models import DownloadProgressEvent
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


@dataclass
class LectureDownloadResult:
    """Outcome of a single episode download attempt."""

    episode_id: str
    title: str
    file_path: Path | None
    status: str  # "completed", "skipped", "failed"
    error: str | None = None


async def download_lectures(
    app: AppContainer,
    module_id: int,
    *,
    on_progress: Callable[[str, DownloadProgressEvent], None] | None = None,
) -> list[LectureDownloadResult]:
    """Orchestrate lecture downloads for a given Opencast module.

    Returns one result per episode discovered (completed / skipped / failed).
    """
    episodes = await app.opencast.get_series_episodes(module_id)
    if not episodes:
        return []

    completed_ids = await _get_completed_ids(app.db, module_id)
    results: list[LectureDownloadResult] = []

    for ep in episodes:
        if ep.episode_id in completed_ids:
            results.append(
                LectureDownloadResult(
                    episode_id=ep.episode_id,
                    title=ep.title,
                    file_path=None,
                    status="skipped",
                )
            )
            continue

        result = await _download_episode(app, module_id, ep.episode_id, ep.title, on_progress)
        results.append(result)

    return results


async def _get_completed_ids(db: aiosqlite.Connection, module_id: int) -> set[str]:
    """Return episode IDs that are already completed or skipped."""
    cursor = await db.execute(
        "SELECT episode_id FROM lecture_downloads"
        " WHERE module_id = ? AND status IN ('completed', 'skipped')",
        (module_id,),
    )
    rows = await cursor.fetchall()
    return {row[0] for row in rows}


async def _download_episode(
    app: AppContainer,
    module_id: int,
    episode_id: str,
    title: str,
    on_progress: Callable[[str, DownloadProgressEvent], None] | None,
) -> LectureDownloadResult:
    """Download a single episode: fetch detail → select track → stream → persist."""
    lecture = await app.opencast.get_episode_detail(module_id, episode_id)
    if lecture is None:
        return LectureDownloadResult(
            episode_id=episode_id,
            title=title,
            file_path=None,
            status="failed",
            error="Episode detail unavailable",
        )

    track = select_best_track(lecture.tracks)
    if track is None:
        return LectureDownloadResult(
            episode_id=episode_id,
            title=title,
            file_path=None,
            status="failed",
            error="No downloadable tracks",
        )

    ext = ext_from_mimetype(track.mimetype)
    safe_series = lecture.series_id.replace("/", "_").replace("..", "_") or "unknown"
    safe_episode = lecture.episode_id.replace("/", "_").replace("..", "_")
    dest: Path = app.settings.data_dir / "lectures" / safe_series / f"{safe_episode}{ext}"

    await _upsert_downloading(
        app.db,
        episode_id,
        module_id,
        lecture.series_id,
        title,
        track.url,
        track.mimetype,
    )

    try:
        async for event in app.lecture_downloader.download_track(track.url, dest):
            if on_progress:
                on_progress(episode_id, event)

        final_path = dest
        if track.mimetype.startswith("video/"):
            extracted = await extract_audio(dest)
            if extracted is not None:
                final_path = extracted

        if await detect_silence(final_path):
            log.info("silent recording detected, skipping", episode_id=episode_id)
            await _mark_skipped(app.db, episode_id, "silent_recording")
            return LectureDownloadResult(
                episode_id=episode_id, title=title, file_path=final_path, status="skipped"
            )

        file_size = final_path.stat().st_size if final_path.exists() else 0
        await _mark_completed(app.db, episode_id, str(final_path), file_size)

        return LectureDownloadResult(
            episode_id=episode_id, title=title, file_path=final_path, status="completed"
        )

    except (LectureDownloadError, OSError) as exc:
        log.warning("lecture download failed", episode_id=episode_id, error=str(exc))
        await _mark_failed(app.db, episode_id, str(exc))
        return LectureDownloadResult(
            episode_id=episode_id, title=title, file_path=None, status="failed", error=str(exc)
        )


async def _upsert_downloading(
    db: aiosqlite.Connection,
    episode_id: str,
    module_id: int,
    series_id: str,
    title: str,
    track_url: str,
    track_mimetype: str,
) -> None:
    await db.execute(
        """INSERT OR REPLACE INTO lecture_downloads
           (episode_id, module_id, series_id, title, track_url, track_mimetype, status, started_at)
           VALUES (?, ?, ?, ?, ?, ?, 'downloading', datetime('now'))""",
        (episode_id, module_id, series_id, title, track_url, track_mimetype),
    )
    await db.commit()


async def _mark_completed(
    db: aiosqlite.Connection,
    episode_id: str,
    file_path: str,
    file_size_bytes: int,
) -> None:
    await db.execute(
        "UPDATE lecture_downloads SET status='completed', file_path=?, "
        "file_size_bytes=?, completed_at=datetime('now') WHERE episode_id=?",
        (file_path, file_size_bytes, episode_id),
    )
    await db.commit()


async def _mark_failed(db: aiosqlite.Connection, episode_id: str, error: str) -> None:
    await db.execute(
        "UPDATE lecture_downloads SET status='failed', error=? WHERE episode_id=?",
        (error, episode_id),
    )
    await db.commit()


async def _mark_skipped(db: aiosqlite.Connection, episode_id: str, skip_reason: str) -> None:
    await db.execute(
        "UPDATE lecture_downloads SET status='skipped', skip_reason=? WHERE episode_id=?",
        (skip_reason, episode_id),
    )
    await db.commit()
