"""Hermes transcription orchestration — transcribe downloaded lectures via Whisper."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.adapters.transcriber import WhisperTranscriber, segments_to_srt
from sophia.domain.errors import TranscriptionError
from sophia.domain.models import HermesConfig
from sophia.infra.schema import (
    lecture_downloads,
    transcript_segments,
    transcriptions,
)
from sophia.services.hermes_setup import load_hermes_config

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

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
    session: AsyncSession,
    module_id: int,
    *,
    on_start: Callable[[str, str], None] | None = None,
    on_complete: Callable[[str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[TranscriptionResult]:
    """Orchestrate transcription for downloaded lectures in a module.

    Returns one result per episode (completed / skipped / failed).
    """
    downloads = await _get_downloads(session, module_id)
    if not downloads:
        return []

    completed_ids = await _get_transcribed_ids(session, module_id)
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
            session,
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


async def _get_downloads(session: AsyncSession, module_id: int) -> list[tuple[str, str, str]]:
    rows = (
        await session.execute(
            select(
                lecture_downloads.c.episode_id,
                lecture_downloads.c.title,
                lecture_downloads.c.file_path,
            ).where(
                lecture_downloads.c.module_id == module_id,
                lecture_downloads.c.status == "completed",
            )
        )
    ).all()
    return [(row.episode_id, row.title, row.file_path) for row in rows]


async def _get_transcribed_ids(session: AsyncSession, module_id: int) -> set[str]:
    query = select(transcriptions.c.episode_id).where(
        transcriptions.c.module_id == module_id,
        transcriptions.c.status == "completed",
    )
    return set((await session.scalars(query)).all())


async def _set_transcription_state(
    session: AsyncSession,
    episode_id: str,
    values: dict[str, object],
) -> None:
    await session.execute(
        update(transcriptions).where(transcriptions.c.episode_id == episode_id).values(**values)
    )


async def _transcribe_episode(
    session: AsyncSession,
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

    statement = pg_insert(transcriptions).values(
        episode_id=episode_id,
        module_id=module_id,
        language="de",
        status="processing",
        started_at=datetime.now(UTC),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[transcriptions.c.episode_id],
            set_={
                "module_id": statement.excluded.module_id,
                "language": statement.excluded.language,
                "status": statement.excluded.status,
                "started_at": statement.excluded.started_at,
                # See hermes_index: a retry must not inherit the previous run's
                # result, which INSERT OR REPLACE used to discard.
                "duration_s": None,
                "segment_count": None,
                "srt_path": None,
                "error": None,
                "completed_at": None,
            },
        )
    )

    try:
        segments: list[TranscriptSegment] = await asyncio.wait_for(
            asyncio.to_thread(transcriber.transcribe, audio_path),
            timeout=_TRANSCRIPTION_TIMEOUT_S,
        )

        srt_content = segments_to_srt(segments)
        srt_path = audio_path.with_suffix(audio_path.suffix + ".srt")
        srt_path.write_text(srt_content, encoding="utf-8")

        await _persist_segments(session, episode_id, segments)
        duration_s = segments[-1].end if segments else 0.0

        await _set_transcription_state(
            session,
            episode_id,
            {
                "status": "completed",
                "segment_count": len(segments),
                "duration_s": duration_s,
                "srt_path": str(srt_path),
                "completed_at": datetime.now(UTC),
            },
        )

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
        await _set_transcription_state(session, episode_id, {"status": "failed", "error": msg})

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
        await _set_transcription_state(
            session,
            episode_id,
            {"status": "failed", "error": str(exc)},
        )

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
    session: AsyncSession,
    episode_id: str,
    segments: list[TranscriptSegment],
) -> None:
    await session.execute(
        delete(transcript_segments).where(transcript_segments.c.episode_id == episode_id)
    )
    if not segments:
        return
    await session.execute(
        insert(transcript_segments),
        [
            {
                "episode_id": episode_id,
                "segment_index": idx,
                "start_time": seg.start,
                "end_time": seg.end,
                "text": seg.text,
            }
            for idx, seg in enumerate(segments)
        ],
    )
