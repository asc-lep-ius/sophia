"""Tests for the Hermes transcription orchestration service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest

from sophia.domain.errors import TranscriptionError
from sophia.domain.models import HermesConfig, TranscriptSegment
from sophia.infra.persistence import run_migrations

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _run_sync(fn: Callable[..., Any], *args: Any) -> Any:
    """Stand-in for asyncio.to_thread that runs the function synchronously."""
    return fn(*args)


@pytest.fixture
async def db():
    db_conn = await aiosqlite.connect(":memory:")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db_conn)
    yield db_conn
    await db_conn.close()


@pytest.fixture
def app(db: aiosqlite.Connection, tmp_path: Path) -> MagicMock:
    mock = MagicMock()
    mock.db = db
    mock.settings.config_dir = tmp_path
    mock.settings.cache_dir = tmp_path / "cache"
    mock.settings.data_dir = tmp_path / "data"
    return mock


def _fake_segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(start=0.0, end=5.0, text="Hello world"),
        TranscriptSegment(start=5.0, end=10.0, text="Second segment"),
        TranscriptSegment(start=10.0, end=15.0, text="Third segment"),
    ]


async def _insert_download(
    db: aiosqlite.Connection,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
    title: str = "Lecture 1",
    file_path: str = "/tmp/audio.mp3",
) -> None:
    await db.execute(
        """INSERT INTO lecture_downloads
           (episode_id, module_id, series_id, title, track_url, track_mimetype,
            file_path, status)
           VALUES (?, ?, 'series-1', ?, 'https://example.com/a.mp3', 'audio/mpeg',
                   ?, 'completed')""",
        (episode_id, module_id, title, file_path),
    )
    await db.commit()


async def _insert_transcription(
    db: aiosqlite.Connection,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
) -> None:
    await db.execute(
        """INSERT INTO transcriptions (episode_id, module_id, status)
           VALUES (?, ?, 'completed')""",
        (episode_id, module_id),
    )
    await db.commit()


@pytest.mark.asyncio
async def test_transcribe_lectures_happy_path(
    app: MagicMock, db: aiosqlite.Connection, tmp_path: Path
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
        results = await transcribe_lectures(app, 42, on_start=on_start, on_complete=on_complete)

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
    cursor = await db.execute(
        "SELECT COUNT(*) FROM transcript_segments WHERE episode_id = 'ep-001'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 3

    # Verify transcription row
    cursor = await db.execute(
        "SELECT status, segment_count FROM transcriptions WHERE episode_id = 'ep-001'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "completed"
    assert row[1] == 3


@pytest.mark.asyncio
async def test_transcribe_lectures_skips_completed(
    app: MagicMock, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    from sophia.services.hermes_transcribe import transcribe_lectures

    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    await _insert_download(db, file_path=str(audio_path))
    await _insert_transcription(db)

    results = await transcribe_lectures(app, 42)

    assert len(results) == 1
    assert results[0].status == "skipped"


@pytest.mark.asyncio
async def test_transcribe_lectures_handles_error(
    app: MagicMock, db: aiosqlite.Connection, tmp_path: Path
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
        results = await transcribe_lectures(app, 42)

    assert len(results) == 1
    r = results[0]
    assert r.status == "failed"
    assert r.error == "model failed"

    cursor = await db.execute(
        "SELECT status, error FROM transcriptions WHERE episode_id = 'ep-001'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "model failed"


@pytest.mark.asyncio
async def test_transcribe_lectures_no_downloads(app: MagicMock, db: aiosqlite.Connection) -> None:
    from sophia.services.hermes_transcribe import transcribe_lectures

    results = await transcribe_lectures(app, 42)
    assert results == []
