"""Hermes transcription orchestration — published captions first, Whisper for the rest.

Two passes produce the same shape of transcript. ``transcribe_from_captions``
runs before anything is downloaded and reads the player's own WebVTT track for
every episode that has one; ``transcribe_lectures`` runs Whisper over the
audio that was downloaded for the episodes that had none. Each row says which
pass wrote it. See docs/captions-as-transcript.md.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.adapters.captions import (
    DEFAULT_CAPTION_LANGUAGE,
    parse_vtt,
    select_caption_track,
)
from sophia.adapters.lecture_downloader import probe_duration
from sophia.adapters.transcriber import WhisperTranscriber, segments_to_srt
from sophia.domain.errors import CaptionError, TranscriptionError
from sophia.domain.models import HermesConfig, TranscriptSource
from sophia.infra.engine import commit_unit
from sophia.infra.schema import (
    lecture_downloads,
    transcript_segments,
    transcriptions,
)
from sophia.services.content_language import get_learning_path_settings
from sophia.services.hermes_catalog import lecture_module_course
from sophia.services.hermes_setup import load_hermes_config, verify_compute_type
from sophia.services.ingestion_settings import get_ingestion_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.domain.models import (
        HermesWhisperConfig,
        Lecture,
        LectureCaption,
        TranscriptSegment,
    )
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
    source: str = TranscriptSource.WHISPER.value


async def resolve_caption_language(session: AsyncSession, module_id: int) -> str:
    """The language whose caption track becomes the transcript.

    The course's transcription language where one is set (#128), otherwise
    its exam language as discovery recorded it; German when the module's
    course is unknown or has no settings yet.
    """
    course_id = await lecture_module_course(session, module_id)
    if course_id is None:
        return DEFAULT_CAPTION_LANGUAGE
    chosen = await resolve_transcription_language(session, module_id)
    if chosen is not None:
        return chosen
    settings = await get_learning_path_settings(session, course_id)
    if settings is None:
        return DEFAULT_CAPTION_LANGUAGE
    return settings.exam_language.value


async def resolve_transcription_language(session: AsyncSession, module_id: int) -> str | None:
    """The language Whisper is told to transcribe the module's lectures in.

    ``None``, the default, means Whisper detects each lecture's language
    itself. Set per course, never per installation: a course taught in
    another language is transcribed correctly with nothing to set up (#128).
    """
    course_id = await lecture_module_course(session, module_id)
    if course_id is None:
        return None
    return (await get_ingestion_settings(session, course_id)).transcription_language


async def transcribe_from_captions(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    *,
    on_start: Callable[[str, str], None] | None = None,
    on_complete: Callable[[str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[TranscriptionResult]:
    """Read the player's captions as the transcript of every episode that has them.

    Runs before the download stage, so a captioned lecture is never
    downloaded. An episode with no usable track, or whose caption file cannot
    be fetched or parsed, is left for Whisper: the reason is logged and
    nothing is written for it. Each transcript is committed as it is stored.
    Returns one result per episode handled here.
    """
    episodes = await app.opencast.get_series_episodes(module_id)
    if not episodes:
        return []

    sources = await _get_transcript_sources(session, module_id)
    excluded = await _get_excluded_downloads(session, module_id)
    language = await resolve_caption_language(session, module_id)
    results: list[TranscriptionResult] = []

    for episode in episodes:
        if cancel_check and cancel_check():
            log.info("captions_cancelled", module_id=module_id, completed=len(results))
            break

        if episode.episode_id in excluded:
            # `lectures discard` promises no further processing, and a silent
            # recording was skipped for a reason; Whisper never read either.
            log.info(
                "captions_skipped",
                episode_id=episode.episode_id,
                reason=f"download is {excluded[episode.episode_id]}",
            )
            continue

        source = sources.get(episode.episode_id)
        if source == TranscriptSource.CAPTIONS.value:
            results.append(_skipped(episode, TranscriptSource.CAPTIONS))
            continue
        if source is not None:
            # Whisper's, and the Whisper pass is what reports it.
            continue

        result = await _transcribe_from_captions(
            app,
            session,
            module_id,
            episode,
            language,
            on_start=on_start,
            on_complete=on_complete,
        )
        if result is not None:
            await commit_unit(session)
            results.append(result)

    return results


def _skipped(episode: Lecture, source: TranscriptSource) -> TranscriptionResult:
    return TranscriptionResult(
        episode_id=episode.episode_id,
        title=episode.title,
        srt_path=None,
        segment_count=0,
        status="skipped",
        source=source.value,
    )


async def _transcribe_from_captions(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    episode: Lecture,
    language: str,
    *,
    on_start: Callable[[str, str], None] | None,
    on_complete: Callable[[str, int], None] | None,
) -> TranscriptionResult | None:
    """Store one episode's caption track as its transcript, or None to leave it to Whisper."""
    detail = await app.opencast.get_episode_detail(module_id, episode.episode_id)
    captions = detail.captions if detail is not None else []
    track = select_caption_track(captions, language)
    if track is None:
        log.info(
            "captions_unavailable",
            episode_id=episode.episode_id,
            source=TranscriptSource.WHISPER.value,
            reason=_unavailable_reason(detail, language),
            offered=[caption.lang for caption in captions],
        )
        return None

    if on_start:
        on_start(episode.episode_id, episode.title)

    try:
        segments = parse_vtt(await app.caption_fetcher.fetch_captions(track.url))
        if not segments:
            raise CaptionError("caption file has no cues")
    except CaptionError as exc:
        log.warning(
            "captions_fallback",
            episode_id=episode.episode_id,
            source=TranscriptSource.WHISPER.value,
            reason=str(exc),
            url=track.url,
        )
        return None

    await _store_caption_transcript(session, module_id, episode, track, segments)

    if on_complete:
        on_complete(episode.episode_id, len(segments))

    log.info(
        "transcript_source",
        episode_id=episode.episode_id,
        source=TranscriptSource.CAPTIONS.value,
        lang=track.lang,
        segments=len(segments),
        url=track.url,
    )
    return TranscriptionResult(
        episode_id=episode.episode_id,
        title=episode.title,
        srt_path=None,
        segment_count=len(segments),
        status="completed",
        source=TranscriptSource.CAPTIONS.value,
    )


def _unavailable_reason(detail: Lecture | None, language: str) -> str:
    if detail is None:
        return "episode detail unavailable"
    wanted = sorted({language, DEFAULT_CAPTION_LANGUAGE})
    return f"no caption track in {' or '.join(repr(lang) for lang in wanted)}"


async def _store_caption_transcript(
    session: AsyncSession,
    module_id: int,
    episode: Lecture,
    track: LectureCaption,
    segments: list[TranscriptSegment],
) -> None:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "module_id": module_id,
        "language": track.lang,
        "status": "completed",
        "source": TranscriptSource.CAPTIONS.value,
        "title": episode.title,
        "caption_url": track.url,
        "segment_count": len(segments),
        "duration_s": segments[-1].end,
        "srt_path": None,
        "error": None,
        "started_at": now,
        "completed_at": now,
    }
    statement = pg_insert(transcriptions).values(episode_id=episode.episode_id, **values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[transcriptions.c.episode_id],
            set_={key: statement.excluded[key] for key in values},
        )
    )
    await _persist_segments(session, episode.episode_id, segments)


async def transcribe_lectures(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    *,
    on_start: Callable[[str, str], None] | None = None,
    on_complete: Callable[[str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[TranscriptionResult]:
    """Orchestrate Whisper transcription for downloaded lectures in a module.

    Each episode's outcome is committed as soon as it is known, so an hour of
    GPU time is not lost to a failure or an interrupt on the episode after it.
    Returns one result per episode (completed / skipped / failed).
    """
    downloads = await _get_downloads(session, module_id)
    if not downloads:
        return []

    completed_ids = await _get_transcribed_ids(session, module_id)
    language = await resolve_transcription_language(session, module_id)
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
            language=language,
            on_start=on_start,
            on_complete=on_complete,
        )
        await commit_unit(session)
        results.append(result)

    return results


def check_whisper_config(app: AppContainer) -> HermesWhisperConfig:
    """Load the Whisper config, failing now if its compute type cannot run on its device."""
    config = load_hermes_config(app.settings.config_dir) or HermesConfig()
    verify_compute_type(config.whisper)
    return config.whisper


def _create_transcriber(app: AppContainer) -> WhisperTranscriber:
    whisper = check_whisper_config(app)
    return WhisperTranscriber(whisper, model_dir=app.settings.cache_dir / "whisper")


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
    return set(await _get_transcript_sources(session, module_id))


async def _get_excluded_downloads(session: AsyncSession, module_id: int) -> dict[str, str]:
    """Episodes whose download row says not to process them, episode id to status."""
    rows = (
        await session.execute(
            select(lecture_downloads.c.episode_id, lecture_downloads.c.status).where(
                lecture_downloads.c.module_id == module_id,
                lecture_downloads.c.status.in_(("discarded", "skipped")),
            )
        )
    ).all()
    return {row.episode_id: row.status for row in rows}


async def _get_transcript_sources(session: AsyncSession, module_id: int) -> dict[str, str]:
    """Completed transcripts of a module, episode id to the source that wrote it."""
    rows = (
        await session.execute(
            select(transcriptions.c.episode_id, transcriptions.c.source).where(
                transcriptions.c.module_id == module_id,
                transcriptions.c.status == "completed",
            )
        )
    ).all()
    return {row.episode_id: row.source for row in rows}


async def _set_transcription_state(
    session: AsyncSession,
    episode_id: str,
    values: dict[str, object],
) -> None:
    await session.execute(
        update(transcriptions).where(transcriptions.c.episode_id == episode_id).values(**values)
    )


async def transcription_timeout(audio_path: Path) -> float:
    """At least the floor, and as long as the recording itself.

    Whisper int8 on the GTX 1070 runs about six times faster than real time,
    so a three-and-a-half-hour lecture needs over thirty minutes; the floor on
    its own timed out six of EP1 2026W's seventeen recordings, and a retry
    could never do better (#128). A run that has not finished by the time it
    could have played the whole lecture is hung, and that still ends.
    """
    duration = await probe_duration(audio_path)
    return max(_TRANSCRIPTION_TIMEOUT_S, duration or 0.0)


async def _transcribe_episode(
    session: AsyncSession,
    transcriber: WhisperTranscriber,
    episode_id: str,
    module_id: int,
    title: str,
    audio_path: Path,
    *,
    language: str | None = None,
    on_start: Callable[[str, str], None] | None = None,
    on_complete: Callable[[str, int], None] | None = None,
) -> TranscriptionResult:
    """Transcribe a single episode: run Whisper → save SRT → persist to DB.

    ``language=None`` has Whisper detect it, and the language it detected is
    what the row records.
    """
    if on_start:
        on_start(episode_id, title)

    log.info(
        "transcript_source",
        episode_id=episode_id,
        source=TranscriptSource.WHISPER.value,
        audio=str(audio_path),
    )

    statement = pg_insert(transcriptions).values(
        episode_id=episode_id,
        module_id=module_id,
        language=language or "auto",
        status="processing",
        source=TranscriptSource.WHISPER.value,
        title=title,
        started_at=datetime.now(UTC),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[transcriptions.c.episode_id],
            set_={
                "module_id": statement.excluded.module_id,
                "language": statement.excluded.language,
                "status": statement.excluded.status,
                "source": statement.excluded.source,
                "title": statement.excluded.title,
                "started_at": statement.excluded.started_at,
                # See hermes_index: a retry must not inherit the previous run's
                # result, which INSERT OR REPLACE used to discard.
                "duration_s": None,
                "segment_count": None,
                "srt_path": None,
                "caption_url": None,
                "error": None,
                "completed_at": None,
            },
        )
    )

    timeout = await transcription_timeout(audio_path)
    try:
        transcript = await asyncio.wait_for(
            asyncio.to_thread(transcriber.transcribe_lecture, audio_path, language),
            timeout=timeout,
        )
        segments: list[TranscriptSegment] = transcript.segments

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
                "language": transcript.language or language or "auto",
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
        msg = f"transcription timed out after {timeout:.0f}s"
        await _set_transcription_state(session, episode_id, {"status": "failed", "error": msg})

        log.error("transcription_timed_out", episode_id=episode_id, timeout=timeout)
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
