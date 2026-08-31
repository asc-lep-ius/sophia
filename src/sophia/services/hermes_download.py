"""Hermes lecture download orchestration — discover, download, extract, persist."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.adapters.lecture_downloader import (
    detect_silence,
    ext_from_mimetype,
    extract_audio,
    select_best_track,
)
from sophia.domain.errors import LectureDownloadError
from sophia.infra.schema import lecture_downloads

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

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
    session: AsyncSession,
    module_id: int,
    *,
    on_progress: Callable[[str, DownloadProgressEvent], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[LectureDownloadResult]:
    """Orchestrate lecture downloads for a given Opencast module.

    Returns one result per episode discovered (completed / skipped / failed).
    """
    episodes = await app.opencast.get_series_episodes(module_id)
    if not episodes:
        return []

    skip_ids = await _get_skip_ids(session, module_id)
    results: list[LectureDownloadResult] = []

    for ep in episodes:
        if cancel_check and cancel_check():
            log.info("download_cancelled", module_id=module_id, completed=len(results))
            break

        if ep.episode_id in skip_ids:
            results.append(
                LectureDownloadResult(
                    episode_id=ep.episode_id,
                    title=ep.title,
                    file_path=None,
                    status="skipped",
                )
            )
            continue

        result = await _download_episode(
            app,
            session,
            module_id,
            ep.episode_id,
            ep.title,
            on_progress,
        )
        results.append(result)

    return results


async def _get_skip_ids(session: AsyncSession, module_id: int) -> set[str]:
    """Return episode IDs that should be skipped (completed, skipped, or discarded)."""
    query = select(lecture_downloads.c.episode_id).where(
        lecture_downloads.c.module_id == module_id,
        lecture_downloads.c.status.in_(("completed", "skipped", "discarded")),
    )
    return set((await session.scalars(query)).all())


async def _download_episode(
    app: AppContainer,
    session: AsyncSession,
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
        session,
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
            await _mark_skipped(session, episode_id, "silent_recording")
            return LectureDownloadResult(
                episode_id=episode_id, title=title, file_path=final_path, status="skipped"
            )

        file_size = final_path.stat().st_size if final_path.exists() else 0
        await _mark_completed(session, episode_id, str(final_path), file_size)

        return LectureDownloadResult(
            episode_id=episode_id, title=title, file_path=final_path, status="completed"
        )

    except (LectureDownloadError, OSError) as exc:
        log.warning("lecture download failed", episode_id=episode_id, error=str(exc))
        await _mark_failed(session, episode_id, str(exc))
        return LectureDownloadResult(
            episode_id=episode_id, title=title, file_path=None, status="failed", error=str(exc)
        )


async def _upsert_downloading(
    session: AsyncSession,
    episode_id: str,
    module_id: int,
    series_id: str,
    title: str,
    track_url: str,
    track_mimetype: str,
) -> None:
    values = {
        "module_id": module_id,
        "series_id": series_id,
        "title": title,
        "track_url": track_url,
        "track_mimetype": track_mimetype,
        "status": "downloading",
        "started_at": datetime.now(UTC),
    }
    statement = pg_insert(lecture_downloads).values(episode_id=episode_id, **values)
    # A retry starts from no result, so the previous attempt's outcome has to go
    # with it: the SQLite original spelled this INSERT OR REPLACE, which deleted
    # the row. Otherwise a failed retry shows status='failed' beside the
    # completed_at and file_path of the run before it.
    #
    # Catalogue metadata is deliberately kept, unlike the REPLACE: lecture_number
    # and missed_at describe the lecture, not the attempt, and are assigned
    # elsewhere. Wiping them on every re-download was a bug worth not porting.
    cleared = dict.fromkeys(
        ("file_path", "file_size_bytes", "error", "completed_at", "skip_reason")
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[lecture_downloads.c.episode_id],
            set_={key: statement.excluded[key] for key in values} | cleared,
        )
    )


async def _set_download_state(
    session: AsyncSession,
    episode_id: str,
    values: dict[str, object],
) -> None:
    await session.execute(
        update(lecture_downloads)
        .where(lecture_downloads.c.episode_id == episode_id)
        .values(**values)
    )


async def _mark_completed(
    session: AsyncSession,
    episode_id: str,
    file_path: str,
    file_size_bytes: int,
) -> None:
    await _set_download_state(
        session,
        episode_id,
        {
            "status": "completed",
            "file_path": file_path,
            "file_size_bytes": file_size_bytes,
            "completed_at": datetime.now(UTC),
        },
    )


async def _mark_failed(session: AsyncSession, episode_id: str, error: str) -> None:
    await _set_download_state(session, episode_id, {"status": "failed", "error": error})


async def _mark_skipped(session: AsyncSession, episode_id: str, skip_reason: str) -> None:
    await _set_download_state(
        session,
        episode_id,
        {"status": "skipped", "skip_reason": skip_reason},
    )
