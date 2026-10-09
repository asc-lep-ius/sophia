"""Tests for the Hermes transcription orchestration service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from structlog.testing import capture_logs

from sophia.domain.errors import CaptionError, TranscriptionError
from sophia.domain.models import HermesConfig, Lecture, LectureCaption, TranscriptSegment

from .._sql import exec_sql

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


def _run_sync(fn: Callable[..., Any], *args: Any) -> Any:
    """Stand-in for asyncio.to_thread that runs the function synchronously."""
    return fn(*args)


@pytest.fixture
def app(db: AsyncSession, tmp_path: Path) -> MagicMock:
    mock = MagicMock()
    mock.db = db
    mock.settings.config_dir = tmp_path
    mock.settings.cache_dir = tmp_path / "cache"
    mock.settings.data_dir = tmp_path / "data"
    return mock


CDN = "https://cdn.video.tuwien.ac.at/static/lecture_tube/engage-player"

# The German track of the EP1 lecture of 2026-01-16, shortened: a trailing
# space after each timing line and a leading space on each text line.
GERMAN_VTT = (
    "WEBVTT\n"
    "\n"
    "00:00:02.910 --> 00:00:06.402 \n"
    " So, willkommen zur letzten Vorlesung Einführung in die Programmierung 1.\n"
    "\n"
    "00:00:08.342 --> 00:00:14.402 \n"
    " Ich wollte heute das zeigen, was ich schon angekündigt habe.\n"
    "\n"
    "01:25:47.442 --> 01:25:50.422 \n"
    " Und dann viel Erfolg in den nächsten Semester.\n"
)
ENGLISH_VTT = "WEBVTT\n\n00:00:02.910 --> 00:00:06.402 \n Welcome to the last lecture.\n"


def _captioned(episode_id: str, title: str, *langs: str) -> Lecture:
    return Lecture(
        episode_id=episode_id,
        title=title,
        series_id="series-1",
        captions=[
            LectureCaption(
                lang=lang,
                url=f"{CDN}/{episode_id}/{lang}/captions.vtt",
                format="vtt",
                label=f"{lang} Waas (Auto generated)",
            )
            for lang in langs
        ],
    )


def _wire_opencast(app: MagicMock, lectures: list[Lecture]) -> None:
    by_id = {lecture.episode_id: lecture for lecture in lectures}
    app.opencast.get_series_episodes = AsyncMock(
        return_value=[
            Lecture(episode_id=lecture.episode_id, title=lecture.title, series_id="")
            for lecture in lectures
        ]
    )
    app.opencast.get_episode_detail = AsyncMock(side_effect=lambda _mid, eid: by_id.get(eid))


def _vtt_for(url: str) -> str:
    return ENGLISH_VTT if "/en/" in url else GERMAN_VTT


async def _fetch_vtt(url: str) -> str:
    return _vtt_for(url)


def _fake_segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(start=0.0, end=5.0, text="Hello world"),
        TranscriptSegment(start=5.0, end=10.0, text="Second segment"),
        TranscriptSegment(start=10.0, end=15.0, text="Third segment"),
    ]


async def _insert_download(
    db: AsyncSession,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
    title: str = "Lecture 1",
    file_path: str = "/tmp/audio.mp3",
) -> None:
    await exec_sql(
        db,
        """INSERT INTO lecture_downloads
           (episode_id, module_id, series_id, title, track_url, track_mimetype,
            file_path, status)
           VALUES (?, ?, 'series-1', ?, 'https://example.com/a.mp3', 'audio/mpeg',
                   ?, 'completed')""",
        (episode_id, module_id, title, file_path),
    )


async def _insert_transcription(
    db: AsyncSession,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
) -> None:
    await exec_sql(
        db,
        """INSERT INTO transcriptions (episode_id, module_id, status)
           VALUES (?, ?, 'completed')""",
        (episode_id, module_id),
    )


@pytest.mark.asyncio
async def test_transcribe_lectures_happy_path(
    app: MagicMock, db: AsyncSession, tmp_path: Path
) -> None:
    from sophia.services.hermes_transcribe import transcribe_lectures

    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    await _insert_download(db, file_path=str(audio_path))

    fake_segs = _fake_segments()
    mock_transcriber = MagicMock()
    mock_transcriber.transcribe.return_value = fake_segs

    on_start = MagicMock()
    on_complete = MagicMock()

    with (
        patch(
            "sophia.services.hermes_transcribe.load_hermes_config",
            return_value=HermesConfig(),
        ),
        patch(
            "sophia.services.hermes_transcribe.WhisperTranscriber",
            return_value=mock_transcriber,
        ),
        patch(
            "sophia.services.hermes_transcribe.asyncio.to_thread",
            side_effect=_run_sync,
        ),
    ):
        results = await transcribe_lectures(app, db, 42, on_start=on_start, on_complete=on_complete)

    assert len(results) == 1
    r = results[0]
    assert r.episode_id == "ep-001"
    assert r.status == "completed"
    assert r.segment_count == 3
    assert r.srt_path is not None
    assert r.srt_path.exists()
    assert "Hello world" in r.srt_path.read_text()

    on_start.assert_called_once_with("ep-001", "Lecture 1")
    on_complete.assert_called_once_with("ep-001", 3)

    # Verify segments persisted to DB
    cursor = await exec_sql(
        db, "SELECT COUNT(*) FROM transcript_segments WHERE episode_id = 'ep-001'"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == 3

    # Verify transcription row
    cursor = await exec_sql(
        db,
        "SELECT status, segment_count, source, title FROM transcriptions "
        "WHERE episode_id = 'ep-001'",
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "completed"
    assert row[1] == 3
    assert row[2] == "whisper"
    assert row[3] == "Lecture 1"


@pytest.mark.asyncio
async def test_transcribe_lectures_skips_completed(
    app: MagicMock, db: AsyncSession, tmp_path: Path
) -> None:
    from sophia.services.hermes_transcribe import transcribe_lectures

    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    await _insert_download(db, file_path=str(audio_path))
    await _insert_transcription(db)

    results = await transcribe_lectures(app, db, 42)

    assert len(results) == 1
    assert results[0].status == "skipped"


@pytest.mark.asyncio
async def test_transcribe_lectures_handles_error(
    app: MagicMock, db: AsyncSession, tmp_path: Path
) -> None:
    from sophia.services.hermes_transcribe import transcribe_lectures

    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    await _insert_download(db, file_path=str(audio_path))

    mock_transcriber = MagicMock()
    mock_transcriber.transcribe.side_effect = TranscriptionError("model failed")

    with (
        patch(
            "sophia.services.hermes_transcribe.load_hermes_config",
            return_value=HermesConfig(),
        ),
        patch(
            "sophia.services.hermes_transcribe.WhisperTranscriber",
            return_value=mock_transcriber,
        ),
        patch(
            "sophia.services.hermes_transcribe.asyncio.to_thread",
            side_effect=_run_sync,
        ),
    ):
        results = await transcribe_lectures(app, db, 42)

    assert len(results) == 1
    r = results[0]
    assert r.status == "failed"
    assert r.error == "model failed"

    cursor = await exec_sql(
        db, "SELECT status, error FROM transcriptions WHERE episode_id = 'ep-001'"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "model failed"


@pytest.mark.asyncio
async def test_transcribe_lectures_no_downloads(app: MagicMock, db: AsyncSession) -> None:
    from sophia.services.hermes_transcribe import transcribe_lectures

    results = await transcribe_lectures(app, db, 42)
    assert results == []


# ---------------------------------------------------------------------------
# transcribe_from_captions — the player's captions before Whisper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_captions_become_the_transcript_without_a_download(
    app: MagicMock, db: AsyncSession
) -> None:
    """A captioned lecture is stored in Whisper's shape, with no download row behind it."""
    from sophia.services.hermes_transcribe import transcribe_from_captions

    _wire_opencast(
        app,
        [
            _captioned("ep-cc", "Vorlesung - VU vom 2026-01-16", "en", "de"),
            _captioned("ep-nc", "Vorlesung - VU vom 2025-11-06"),
        ],
    )
    app.caption_fetcher.fetch_captions = AsyncMock(side_effect=_fetch_vtt)
    on_start = MagicMock()
    on_complete = MagicMock()

    with capture_logs() as logs:
        results = await transcribe_from_captions(
            app, db, 42, on_start=on_start, on_complete=on_complete
        )

    assert [(r.episode_id, r.status, r.source, r.segment_count) for r in results] == [
        ("ep-cc", "completed", "captions", 3),
    ]
    assert results[0].srt_path is None
    app.caption_fetcher.fetch_captions.assert_awaited_once_with(f"{CDN}/ep-cc/de/captions.vtt")
    on_start.assert_called_once_with("ep-cc", "Vorlesung - VU vom 2026-01-16")
    on_complete.assert_called_once_with("ep-cc", 3)

    row = (
        await exec_sql(
            db,
            "SELECT status, source, language, title, caption_url, segment_count, duration_s, "
            "srt_path FROM transcriptions WHERE episode_id = 'ep-cc'",
        )
    ).fetchone()
    assert row is not None
    assert tuple(row[:5]) == (
        "completed",
        "captions",
        "de",
        "Vorlesung - VU vom 2026-01-16",
        f"{CDN}/ep-cc/de/captions.vtt",
    )
    assert row[5] == 3
    assert row[6] == pytest.approx(1 * 3600 + 25 * 60 + 50.422)
    assert row[7] is None

    segments = (
        await exec_sql(
            db,
            "SELECT segment_index, start_time, end_time, text FROM transcript_segments "
            "WHERE episode_id = 'ep-cc' ORDER BY segment_index",
        )
    ).fetchall()
    assert [(seg[0], seg[1], seg[2]) for seg in segments] == [
        (0, pytest.approx(2.91), pytest.approx(6.402)),
        (1, pytest.approx(8.342), pytest.approx(14.402)),
        (2, pytest.approx(5147.442), pytest.approx(5150.422)),
    ]
    assert segments[0][3].startswith("So, willkommen zur letzten Vorlesung")

    downloads = (await exec_sql(db, "SELECT count(*) FROM lecture_downloads")).fetchone()
    assert downloads is not None
    assert downloads[0] == 0

    sources = [entry for entry in logs if entry["event"] == "transcript_source"]
    assert [(entry["episode_id"], entry["source"]) for entry in sources] == [("ep-cc", "captions")]
    unavailable = [entry for entry in logs if entry["event"] == "captions_unavailable"]
    assert [(entry["episode_id"], entry["source"]) for entry in unavailable] == [
        ("ep-nc", "whisper")
    ]


@pytest.mark.asyncio
async def test_captions_prefer_the_course_language_and_fall_back_to_german(
    app: MagicMock, db: AsyncSession
) -> None:
    """Fork answered 2026-10-09: the course's language first, German otherwise."""
    from sophia.services.hermes_transcribe import transcribe_from_captions

    await exec_sql(
        db,
        "INSERT INTO lecture_modules (module_id, course_name, course_shortname, course_id) "
        "VALUES (42, 'Programming in English', 'PIE', '12')",
    )
    await exec_sql(
        db,
        "INSERT INTO learning_path_settings (course_id, exam_language) VALUES (12, 'en')",
    )
    _wire_opencast(
        app,
        [
            _captioned("ep-both", "Both tracks", "de", "en"),
            _captioned("ep-de", "German only", "de"),
        ],
    )
    app.caption_fetcher.fetch_captions = AsyncMock(side_effect=_fetch_vtt)

    results = await transcribe_from_captions(app, db, 42)

    assert [(r.episode_id, r.status) for r in results] == [
        ("ep-both", "completed"),
        ("ep-de", "completed"),
    ]
    assert app.caption_fetcher.fetch_captions.await_args_list == [
        (((f"{CDN}/ep-both/en/captions.vtt"),),),
        (((f"{CDN}/ep-de/de/captions.vtt"),),),
    ]
    languages = (
        await exec_sql(db, "SELECT episode_id, language FROM transcriptions ORDER BY episode_id")
    ).fetchall()
    assert [tuple(row) for row in languages] == [("ep-both", "en"), ("ep-de", "de")]


@pytest.mark.asyncio
async def test_captions_already_read_are_skipped_and_whisper_rows_left_alone(
    app: MagicMock, db: AsyncSession
) -> None:
    from sophia.services.hermes_transcribe import transcribe_from_captions

    await exec_sql(
        db,
        "INSERT INTO transcriptions (episode_id, module_id, status, source, title) "
        "VALUES ('ep-cc', 42, 'completed', 'captions', 'Captioned')",
    )
    await _insert_download(db, episode_id="ep-w", title="Whispered")
    await exec_sql(
        db,
        "INSERT INTO transcriptions (episode_id, module_id, status) "
        "VALUES ('ep-w', 42, 'completed')",
    )
    _wire_opencast(
        app, [_captioned("ep-cc", "Captioned", "de"), _captioned("ep-w", "Whispered", "de")]
    )
    app.caption_fetcher.fetch_captions = AsyncMock(side_effect=_fetch_vtt)

    results = await transcribe_from_captions(app, db, 42)

    assert [(r.episode_id, r.status, r.source) for r in results] == [
        ("ep-cc", "skipped", "captions"),
    ]
    app.caption_fetcher.fetch_captions.assert_not_awaited()
    app.opencast.get_episode_detail.assert_not_awaited()


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        pytest.param(CaptionError("HTTP 404 fetching captions"), "HTTP 404", id="fetch"),
        pytest.param("<html>Not Found</html>", "not a WebVTT", id="parse"),
        pytest.param("WEBVTT\n", "no cues", id="empty"),
    ],
)
@pytest.mark.asyncio
async def test_a_caption_file_that_cannot_be_read_falls_back_to_whisper(
    app: MagicMock,
    db: AsyncSession,
    failure: CaptionError | str,
    reason: str,
) -> None:
    """The reason is logged, nothing is written for that episode, and the run continues."""
    from sophia.services.hermes_transcribe import transcribe_from_captions

    _wire_opencast(app, [_captioned("ep-bad", "Broken", "de"), _captioned("ep-ok", "Fine", "de")])

    async def fetch(url: str) -> str:
        if "/ep-bad/" in url:
            if isinstance(failure, CaptionError):
                raise failure
            return failure
        return GERMAN_VTT

    app.caption_fetcher.fetch_captions = AsyncMock(side_effect=fetch)

    with capture_logs() as logs:
        results = await transcribe_from_captions(app, db, 42)

    assert [(r.episode_id, r.status, r.source) for r in results] == [
        ("ep-ok", "completed", "captions"),
    ]
    rows = (await exec_sql(db, "SELECT episode_id FROM transcriptions")).fetchall()
    assert [row[0] for row in rows] == ["ep-ok"]

    fallbacks = [entry for entry in logs if entry["event"] == "captions_fallback"]
    assert len(fallbacks) == 1
    assert fallbacks[0]["episode_id"] == "ep-bad"
    assert fallbacks[0]["source"] == "whisper"
    assert fallbacks[0]["log_level"] == "warning"
    assert reason in fallbacks[0]["reason"]


@pytest.mark.asyncio
async def test_captions_pass_with_no_episodes(app: MagicMock, db: AsyncSession) -> None:
    from sophia.services.hermes_transcribe import transcribe_from_captions

    app.opencast.get_series_episodes = AsyncMock(return_value=[])

    assert await transcribe_from_captions(app, db, 42) == []


@pytest.mark.asyncio
async def test_captions_pass_honours_cancellation(app: MagicMock, db: AsyncSession) -> None:
    from sophia.services.hermes_transcribe import transcribe_from_captions

    _wire_opencast(app, [_captioned("ep-1", "One", "de"), _captioned("ep-2", "Two", "de")])
    app.caption_fetcher.fetch_captions = AsyncMock(side_effect=_fetch_vtt)
    calls = 0

    def cancel_after_one() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    results = await transcribe_from_captions(app, db, 42, cancel_check=cancel_after_one)

    assert [r.episode_id for r in results] == ["ep-1"]
