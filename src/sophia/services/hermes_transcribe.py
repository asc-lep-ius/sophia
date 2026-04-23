"""Hermes transcription orchestration — transcribe downloaded lectures via Whisper."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from sophia.adapters.transcriber import WhisperTranscriber, segments_to_srt
from sophia.domain.errors import TranscriptionError
from sophia.domain.models import HermesConfig
from sophia.services.hermes_setup import load_hermes_config

if TYPE_CHECKING:
    from collections.abc import Callable

    import aiosqlite

    from sophia.domain.models import TranscriptSegment
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# Generous flat ceiling — no duration metadata available at this point
_TRANSCRIPTION_TIMEOUT_S: float = 1800.0


@dataclass
class TranscriptionResult:
    """Outcome of a single episode transcription attempt."""

    episode_id: str
    title: str
    srt_path: Path | None
    segment_count: int
    status: str  # "completed", "skipped", "failed"
    error: str | None = None


async def transcribe_lectures(
    app: AppContainer,
    module_id: int,
    *,
    episode_ids: set[str] | None = None,
    on_start: Callable[[str, str], None] | None = None,
    on_complete: Callable[[str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[TranscriptionResult]:
    """Orchestrate transcription for downloaded lectures in a module.

    Returns one result per episode (completed / skipped / failed).
    """
    downloads = await _get_downloads(app.db, module_id)
    if episode_ids is not None:
        downloads = [row for row in downloads if row[0] in episode_ids]
    if not downloads:
        return []

    completed_ids = await _get_transcribed_ids(app.db, module_id)
    results: list[TranscriptionResult] = []
    transcriber: WhisperTranscriber | None = None

    for episode_id, title, file_path in downloads:
        if cancel_check and cancel_check():
            log.info("transcription_cancelled", module_id=module_id, completed=len(results))
            break

        if episode_id in completed_ids:
            results.append(
                TranscriptionResult(
                    episode_id=episode_id,
                    title=title,
                    srt_path=None,
                    segment_count=0,
                    status="skipped",
                )
            )
            continue

        if transcriber is None:
            transcriber = _create_transcriber(app)

        result = await _transcribe_episode(
            app.db,
            transcriber,
            episode_id,
            module_id,
            title,
            Path(file_path),
            on_start=on_start,
            on_complete=on_complete,
        )
        results.append(result)

    return results


def _create_transcriber(app: AppContainer) -> WhisperTranscriber:
    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        config = HermesConfig()
    return WhisperTranscriber(config.whisper, model_dir=app.settings.cache_dir / "whisper")


async def _get_downloads(db: aiosqlite.Connection, module_id: int) -> list[tuple[str, str, str]]:
    cursor = await db.execute(
        "SELECT episode_id, title, file_path FROM lecture_downloads "
        "WHERE module_id = ? AND status = 'completed'",
        (module_id,),
    )
    return await cursor.fetchall()  # type: ignore[return-value]


async def _get_transcribed_ids(db: aiosqlite.Connection, module_id: int) -> set[str]:
    cursor = await db.execute(
        "SELECT episode_id FROM transcriptions WHERE module_id = ? AND status = 'completed'",
        (module_id,),
    )
    rows = await cursor.fetchall()
    return {row[0] for row in rows}


async def _transcribe_episode(
    db: aiosqlite.Connection,
    transcriber: WhisperTranscriber,
    episode_id: str,
    module_id: int,
    title: str,
    audio_path: Path,
    *,
    on_start: Callable[[str, str], None] | None = None,
    on_complete: Callable[[str, int], None] | None = None,
) -> TranscriptionResult:
    """Transcribe a single episode: run Whisper → save SRT → persist to DB."""
    if on_start:
        on_start(episode_id, title)

    await db.execute(
        "INSERT OR REPLACE INTO transcriptions "
        "(episode_id, module_id, language, status, started_at) "
        "VALUES (?, ?, 'de', 'processing', datetime('now'))",
        (episode_id, module_id),
    )
    await db.commit()

    try:
        segments: list[TranscriptSegment] = await asyncio.wait_for(
            asyncio.to_thread(transcriber.transcribe, audio_path),
            timeout=_TRANSCRIPTION_TIMEOUT_S,
        )

        srt_content = segments_to_srt(segments)
        srt_path = audio_path.with_suffix(audio_path.suffix + ".srt")
        srt_path.write_text(srt_content, encoding="utf-8")

        await _persist_segments(db, episode_id, segments)
        duration_s = segments[-1].end if segments else 0.0

        await db.execute(
            "UPDATE transcriptions SET status='completed', segment_count=?, "
            "duration_s=?, srt_path=?, completed_at=datetime('now') WHERE episode_id=?",
            (len(segments), duration_s, str(srt_path), episode_id),
        )
        await db.commit()

        if on_complete:
            on_complete(episode_id, len(segments))

        log.info("transcription_completed", episode_id=episode_id, segments=len(segments))
        return TranscriptionResult(
            episode_id=episode_id,
            title=title,
            srt_path=srt_path,
            segment_count=len(segments),
            status="completed",
        )

    except TimeoutError:
        msg = f"transcription timed out after {_TRANSCRIPTION_TIMEOUT_S}s"
        await db.execute(
            "UPDATE transcriptions SET status='failed', error=? WHERE episode_id=?",
            (msg, episode_id),
        )
        await db.commit()

        log.error(
            "transcription_timed_out",
            episode_id=episode_id,
            timeout=_TRANSCRIPTION_TIMEOUT_S,
        )
        return TranscriptionResult(
            episode_id=episode_id,
            title=title,
            srt_path=None,
            segment_count=0,
            status="failed",
            error=msg,
        )

    except (TranscriptionError, OSError) as exc:
        await db.execute(
            "UPDATE transcriptions SET status='failed', error=? WHERE episode_id=?",
            (str(exc), episode_id),
        )
        await db.commit()

        log.error("transcription_failed", episode_id=episode_id, error=str(exc))
        return TranscriptionResult(
            episode_id=episode_id,
            title=title,
            srt_path=None,
            segment_count=0,
            status="failed",
            error=str(exc),
        )


async def _persist_segments(
    db: aiosqlite.Connection,
    episode_id: str,
    segments: list[TranscriptSegment],
) -> None:
    await db.execute("DELETE FROM transcript_segments WHERE episode_id = ?", (episode_id,))
    await db.executemany(
        "INSERT INTO transcript_segments "
        "(episode_id, segment_index, start_time, end_time, text) "
        "VALUES (?, ?, ?, ?, ?)",
        [(episode_id, idx, seg.start, seg.end, seg.text) for idx, seg in enumerate(segments)],
    )
