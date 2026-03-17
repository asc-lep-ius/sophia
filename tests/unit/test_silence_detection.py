"""Tests for silence detection and its integration in the download flow."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from sophia.adapters.lecture_downloader import detect_silence
from sophia.domain.models import DownloadStatus
from sophia.infra.persistence import run_migrations

if TYPE_CHECKING:
    from pathlib import Path


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
async def db():
    db_conn = await aiosqlite.connect(":memory:")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db_conn)
    yield db_conn
    await db_conn.close()


# ------------------------------------------------------------------
# detect_silence() — unit tests with mocked ffmpeg/ffprobe
# ------------------------------------------------------------------

_FFPROBE_DURATION_120 = b"120.0\n"

_FFMPEG_MOSTLY_SILENT = (
    b"[silencedetect @ 0x1234] silence_start: 0.000000\n"
    b"[silencedetect @ 0x1234] silence_end: 100.000000 | silence_duration: 100.000000\n"
)

_FFMPEG_HAS_SPEECH = (
    b"[silencedetect @ 0x1234] silence_start: 10.000000\n"
    b"[silencedetect @ 0x1234] silence_end: 15.000000 | silence_duration: 5.000000\n"
    b"[silencedetect @ 0x1234] silence_start: 50.000000\n"
    b"[silencedetect @ 0x1234] silence_end: 55.000000 | silence_duration: 5.000000\n"
)

_FFMPEG_NO_SILENCE = b"some other ffmpeg output\n"

# 100/120 = 0.833 > 0.8 threshold
_FFMPEG_EDGE_ABOVE = (
    b"[silencedetect @ 0x1234] silence_start: 0.000000\n"
    b"[silencedetect @ 0x1234] silence_end: 97.000000 | silence_duration: 97.000000\n"
)

# 50/120 = 0.416 < 0.8
_FFMPEG_EDGE_BELOW = (
    b"[silencedetect @ 0x1234] silence_start: 0.000000\n"
    b"[silencedetect @ 0x1234] silence_end: 50.000000 | silence_duration: 50.000000\n"
)


def _mock_subprocess(ffprobe_stdout: bytes, ffmpeg_stderr: bytes, returncode: int = 0):
    """Create a side_effect for create_subprocess_exec that handles ffprobe and ffmpeg calls."""

    async def _side_effect(*args, **_kwargs):
        mock_proc = AsyncMock()
        mock_proc.returncode = returncode
        if args[0] == "ffprobe":
            mock_proc.communicate.return_value = (ffprobe_stdout, b"")
        else:
            mock_proc.communicate.return_value = (b"", ffmpeg_stderr)
        return mock_proc

    return _side_effect


@pytest.mark.parametrize(
    ("ffmpeg_stderr", "expected", "description"),
    [
        (_FFMPEG_MOSTLY_SILENT, True, "mostly_silent_83pct"),
        (_FFMPEG_HAS_SPEECH, False, "has_speech_8pct"),
        (_FFMPEG_NO_SILENCE, False, "no_silence_detected"),
        (_FFMPEG_EDGE_ABOVE, True, "edge_above_80pct"),
        (_FFMPEG_EDGE_BELOW, False, "edge_below_80pct"),
    ],
    ids=["mostly_silent", "has_speech", "no_silence", "edge_above", "edge_below"],
)
async def test_detect_silence_scenarios(
    tmp_path: Path, ffmpeg_stderr: bytes, expected: bool, description: str
) -> None:
    audio = tmp_path / "lecture.m4a"
    audio.write_bytes(b"\x00" * 100)

    with patch("sophia.adapters.lecture_downloader.asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _mock_subprocess(_FFPROBE_DURATION_120, ffmpeg_stderr)
        result = await detect_silence(audio)

    assert result is expected, f"Failed for scenario: {description}"


async def test_detect_silence_ffmpeg_missing(tmp_path: Path) -> None:
    """When ffmpeg isn't found, fail-open: return False."""
    audio = tmp_path / "lecture.m4a"
    audio.write_bytes(b"\x00" * 100)

    with patch("sophia.adapters.lecture_downloader.shutil.which", return_value=None):
        result = await detect_silence(audio)

    assert result is False


async def test_detect_silence_ffprobe_fails(tmp_path: Path) -> None:
    """When ffprobe returns non-zero, fail-open: return False."""
    audio = tmp_path / "lecture.m4a"
    audio.write_bytes(b"\x00" * 100)

    with patch("sophia.adapters.lecture_downloader.asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _mock_subprocess(b"", b"", returncode=1)
        result = await detect_silence(audio)

    assert result is False


async def test_detect_silence_ffprobe_returns_zero_duration(tmp_path: Path) -> None:
    """Zero-length file should not crash — fail-open."""
    audio = tmp_path / "lecture.m4a"
    audio.write_bytes(b"\x00" * 100)

    with patch("sophia.adapters.lecture_downloader.asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = _mock_subprocess(b"0.0\n", _FFMPEG_MOSTLY_SILENT)
        result = await detect_silence(audio)

    assert result is False


# ------------------------------------------------------------------
# DownloadStatus enum — SKIPPED state and transitions
# ------------------------------------------------------------------


def test_skipped_status_exists() -> None:
    assert DownloadStatus.SKIPPED == "skipped"


def test_downloading_to_skipped_transition_allowed() -> None:
    from sophia.domain.models import _ALLOWED_TRANSITIONS

    assert DownloadStatus.SKIPPED in _ALLOWED_TRANSITIONS[DownloadStatus.DOWNLOADING]


def test_skipped_to_queued_transition_allowed() -> None:
    """Retry: a skipped episode can be re-queued."""
    from sophia.domain.models import _ALLOWED_TRANSITIONS

    assert DownloadStatus.QUEUED in _ALLOWED_TRANSITIONS[DownloadStatus.SKIPPED]


# ------------------------------------------------------------------
# DB migration — skip_reason column exists
# ------------------------------------------------------------------


async def test_migration_adds_skip_reason_column(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(lecture_downloads)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "skip_reason" in columns


# ------------------------------------------------------------------
# Download flow integration — detect_silence wired in
# ------------------------------------------------------------------


@pytest.fixture
def app(db: aiosqlite.Connection, tmp_path: Path) -> MagicMock:
    mock = MagicMock()
    mock.db = db
    mock.settings.data_dir = tmp_path
    mock.opencast = AsyncMock()
    mock.lecture_downloader = AsyncMock()
    return mock


async def test_download_marks_silent_episode_as_skipped(
    app: MagicMock, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    from sophia.domain.models import Lecture, LectureTrack
    from sophia.services.hermes_download import _download_episode

    track = LectureTrack(
        flavor="presenter/m4a", url="https://a/a.m4a", mimetype="audio/m4a", resolution=""
    )
    lecture = Lecture(
        episode_id="ep-silent", title="Empty Room", series_id="series-1", tracks=[track]
    )
    app.opencast.get_episode_detail.return_value = lecture

    dest_dir = tmp_path / "lectures" / "series-1"
    dest_dir.mkdir(parents=True)
    dest_file = dest_dir / "ep-silent.m4a"
    dest_file.write_bytes(b"\x00" * 100)

    async def _fake_download(*_a, **_kw):
        return
        yield  # noqa: RET504

    app.lecture_downloader.download_track = MagicMock(return_value=_fake_download())

    with patch("sophia.services.hermes_download.detect_silence", return_value=True):
        result = await _download_episode(app, 42, "ep-silent", "Empty Room", None)

    assert result.status == "skipped"

    cursor = await db.execute(
        "SELECT status, skip_reason FROM lecture_downloads WHERE episode_id = 'ep-silent'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "skipped"
    assert row[1] == "silent_recording"


async def test_download_proceeds_normally_when_not_silent(
    app: MagicMock, db: aiosqlite.Connection, tmp_path: Path
) -> None:
    from sophia.domain.models import Lecture, LectureTrack
    from sophia.services.hermes_download import _download_episode

    track = LectureTrack(
        flavor="presenter/m4a", url="https://a/a.m4a", mimetype="audio/m4a", resolution=""
    )
    lecture = Lecture(
        episode_id="ep-normal", title="Real Lecture", series_id="series-1", tracks=[track]
    )
    app.opencast.get_episode_detail.return_value = lecture

    dest_dir = tmp_path / "lectures" / "series-1"
    dest_dir.mkdir(parents=True)
    dest_file = dest_dir / "ep-normal.m4a"
    dest_file.write_bytes(b"\x00" * 100)

    async def _fake_download(*_a, **_kw):
        return
        yield  # noqa: RET504

    app.lecture_downloader.download_track = MagicMock(return_value=_fake_download())

    with patch("sophia.services.hermes_download.detect_silence", return_value=False):
        result = await _download_episode(app, 42, "ep-normal", "Real Lecture", None)

    assert result.status == "completed"
