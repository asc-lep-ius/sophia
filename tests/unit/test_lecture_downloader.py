"""Tests for the lecture downloader adapter — track selection, HTTP download, audio extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from sophia.adapters.lecture_downloader import (
    HttpLectureDownloader,
    ext_from_mimetype,
    extract_audio,
    select_best_track,
)
from sophia.domain.errors import LectureDownloadError
from sophia.domain.models import DownloadProgressEvent, LectureTrack
from sophia.domain.ports import LectureDownloader

if TYPE_CHECKING:
    from pathlib import Path


# ------------------------------------------------------------------
# Structural conformance
# ------------------------------------------------------------------


def _conforms_to(instance: object, protocol: type) -> bool:
    """Check structural conformance without requiring @runtime_checkable."""
    hints = {
        name
        for name in dir(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }
    return all(hasattr(instance, name) for name in hints)


def test_http_lecture_downloader_conforms_to_protocol() -> None:
    client = httpx.AsyncClient()
    downloader = HttpLectureDownloader(client)
    assert _conforms_to(downloader, LectureDownloader)


# ------------------------------------------------------------------
# Track selection — pure unit tests
# ------------------------------------------------------------------


def test_select_best_track_prefers_audio() -> None:
    tracks = [
        LectureTrack(
            flavor="presenter/mp4",
            url="https://a/v.mp4",
            mimetype="video/mp4",
            resolution="1920x1080",
        ),
        LectureTrack(
            flavor="presenter/m4a",
            url="https://a/a.m4a",
            mimetype="audio/m4a",
            resolution="",
        ),
    ]
    result = select_best_track(tracks)
    assert result is not None
    assert result.mimetype.startswith("audio/")


def test_select_best_track_lowest_resolution() -> None:
    tracks = [
        LectureTrack(
            flavor="presenter/mp4",
            url="https://a/hd.mp4",
            mimetype="video/mp4",
            resolution="1920x1080",
        ),
        LectureTrack(
            flavor="presenter/mp4",
            url="https://a/sd.mp4",
            mimetype="video/mp4",
            resolution="640x480",
        ),
        LectureTrack(
            flavor="presenter/mp4",
            url="https://a/md.mp4",
            mimetype="video/mp4",
            resolution="1280x720",
        ),
    ]
    result = select_best_track(tracks)
    assert result is not None
    assert result.resolution == "640x480"


def test_select_best_track_no_tracks() -> None:
    assert select_best_track([]) is None


def test_select_best_track_unknown_resolution_sorted_last() -> None:
    tracks = [
        LectureTrack(
            flavor="presenter/mp4",
            url="https://a/unk.mp4",
            mimetype="video/mp4",
            resolution="",
        ),
        LectureTrack(
            flavor="presenter/mp4",
            url="https://a/sd.mp4",
            mimetype="video/mp4",
            resolution="640x480",
        ),
    ]
    result = select_best_track(tracks)
    assert result is not None
    assert result.resolution == "640x480"


def test_select_best_track_video_only() -> None:
    tracks = [
        LectureTrack(
            flavor="presenter/mp4",
            url="https://a/v.mp4",
            mimetype="video/mp4",
            resolution="1280x720",
        ),
    ]
    result = select_best_track(tracks)
    assert result is not None
    assert result.url == "https://a/v.mp4"


# ------------------------------------------------------------------
# ext_from_mimetype
# ------------------------------------------------------------------

_KNOWN_MIMETYPES = [
    ("video/mp4", ".mp4"),
    ("video/webm", ".webm"),
    ("audio/mp3", ".mp3"),
    ("audio/mpeg", ".mp3"),
    ("audio/ogg", ".ogg"),
    ("audio/m4a", ".m4a"),
    ("audio/aac", ".aac"),
]


@pytest.mark.parametrize(("mimetype", "expected"), _KNOWN_MIMETYPES)
def test_ext_from_mimetype_known(mimetype: str, expected: str) -> None:
    assert ext_from_mimetype(mimetype) == expected


def test_ext_from_mimetype_unknown() -> None:
    assert ext_from_mimetype("application/octet-stream") == ".mp4"


# ------------------------------------------------------------------
# Download tests (respx HTTP mocking)
# ------------------------------------------------------------------

DOWNLOAD_URL = "https://cdn.example.com/lecture.mp4"
CHUNK = b"A" * 65_536  # 64 KiB


@respx.mock
async def test_download_track_streams_to_file(tmp_path: Path) -> None:
    body = CHUNK * 4  # 256 KiB
    respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(200, content=body, headers={"content-length": str(len(body))})
    )

    dest = tmp_path / "lecture.mp4"
    async with httpx.AsyncClient() as client:
        downloader = HttpLectureDownloader(client)
        events: list[DownloadProgressEvent] = []
        async for event in downloader.download_track(DOWNLOAD_URL, dest):
            events.append(event)

    assert dest.read_bytes() == body
    assert len(events) > 0
    assert events[-1].bytes_downloaded == len(body)


@respx.mock
async def test_download_track_resume(tmp_path: Path) -> None:
    partial = b"B" * 100
    remaining = b"C" * 200
    dest = tmp_path / "lecture.mp4"
    dest.write_bytes(partial)

    def _check_range(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("range") == f"bytes={len(partial)}-"
        return httpx.Response(
            206,
            content=remaining,
            headers={"content-length": str(len(remaining))},
        )

    respx.get(DOWNLOAD_URL).mock(side_effect=_check_range)

    async with httpx.AsyncClient() as client:
        downloader = HttpLectureDownloader(client)
        events: list[DownloadProgressEvent] = []
        async for event in downloader.download_track(DOWNLOAD_URL, dest):
            events.append(event)

    assert dest.read_bytes() == partial + remaining


@respx.mock
async def test_download_track_already_complete(tmp_path: Path) -> None:
    dest = tmp_path / "lecture.mp4"
    existing = b"D" * 500
    dest.write_bytes(existing)

    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(416))

    async with httpx.AsyncClient() as client:
        downloader = HttpLectureDownloader(client)
        events: list[DownloadProgressEvent] = []
        async for event in downloader.download_track(DOWNLOAD_URL, dest):
            events.append(event)

    assert dest.read_bytes() == existing


@respx.mock
async def test_download_track_http_error(tmp_path: Path) -> None:
    dest = tmp_path / "lecture.mp4"
    respx.get(DOWNLOAD_URL).mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as client:
        downloader = HttpLectureDownloader(client)
        with pytest.raises(LectureDownloadError):
            async for _ in downloader.download_track(DOWNLOAD_URL, dest):
                pass


# ------------------------------------------------------------------
# Audio extraction (mock subprocess)
# ------------------------------------------------------------------


async def test_extract_audio_success(tmp_path: Path) -> None:
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"fake video content")

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await extract_audio(video)

    expected = tmp_path / "lecture.m4a"
    assert result == expected
    assert not video.exists()


async def test_extract_audio_no_ffmpeg(tmp_path: Path) -> None:
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"fake video content")

    with patch("shutil.which", return_value=None):
        result = await extract_audio(video)

    assert result is None
    assert video.exists()


async def test_extract_audio_ffmpeg_fails(tmp_path: Path) -> None:
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"fake video content")

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"some error"))

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await extract_audio(video)

    assert result is None
    assert video.exists()
