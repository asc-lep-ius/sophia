"""Lecture download adapter — track selection, streaming HTTP download, audio extraction.

Implements the ``LectureDownloader`` protocol for downloading Opencast
lecture media with resume support and optional ffmpeg audio extraction.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    import httpx

from sophia.domain.errors import LectureDownloadError
from sophia.domain.models import DownloadProgressEvent, LectureTrack

log = structlog.get_logger()

_CHUNK_SIZE = 65_536  # 64 KiB

_MIMETYPE_EXT: dict[str, str] = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "audio/mp3": ".mp3",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
}


def ext_from_mimetype(mimetype: str) -> str:
    """Map a MIME type to a file extension, defaulting to ``.mp4``."""
    return _MIMETYPE_EXT.get(mimetype, ".mp4")


def _resolution_area(track: LectureTrack) -> int:
    """Parse ``WxH`` resolution string into pixel area; unknown → max int."""
    if not track.resolution:
        return 2**31
    parts = track.resolution.split("x")
    if len(parts) != 2:  # noqa: PLR2004
        return 2**31
    try:
        return int(parts[0]) * int(parts[1])
    except ValueError:
        return 2**31


def select_best_track(tracks: list[LectureTrack]) -> LectureTrack | None:
    """Pick the best track: prefer audio-only, then lowest-resolution video."""
    if not tracks:
        return None

    audio = [t for t in tracks if t.mimetype.startswith("audio/")]
    if audio:
        return audio[0]

    video = [t for t in tracks if t.mimetype.startswith("video/")]
    if video:
        return min(video, key=_resolution_area)

    return tracks[0]


async def extract_audio(video_path: Path) -> Path | None:
    """Extract audio from *video_path* via ffmpeg, returning the ``.m4a`` path.

    Deletes the original video on success.  Returns ``None`` (keeping the
    original file) when ffmpeg is unavailable or fails.
    """
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg not found, skipping audio extraction")
        return None

    audio_path = video_path.with_suffix(".m4a")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i",
        str(video_path),
        "-vn",
        "-c:a",
        "copy",
        str(audio_path),
        "-y",
        "-loglevel",
        "error",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        log.warning("ffmpeg failed", stderr=stderr.decode(errors="replace"))
        return None

    video_path.unlink()
    return audio_path


async def detect_silence(audio_path: Path, threshold_ratio: float = 0.8) -> bool:
    """Return True if *audio_path* is mostly silent (empty-room recording).

    Uses ffprobe for duration and ffmpeg silencedetect for silence spans.
    Fails open: returns False if tools are missing or fail, so downloads
    are never blocked by detection errors.
    """
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        log.warning("ffprobe/ffmpeg not found, skipping silence detection")
        return False

    # Get total duration via ffprobe
    probe = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await probe.communicate()
    if probe.returncode != 0:
        log.warning("ffprobe failed", path=str(audio_path))
        return False

    try:
        total_duration = float(stdout.strip())
    except (ValueError, TypeError):
        log.warning("could not parse duration", raw=stdout)
        return False

    if total_duration <= 0:
        return False

    # Run silencedetect
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", str(audio_path),
        "-af", "silencedetect=noise=-30dB:d=2",
        "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        log.warning("ffmpeg silencedetect failed", path=str(audio_path))
        return False

    # Sum silence durations from stderr lines like:
    # [silencedetect @ 0x...] silence_end: 120.5 | silence_duration: 120.5
    total_silence = 0.0
    for match in re.finditer(r"silence_duration:\s*([\d.]+)", stderr.decode(errors="replace")):
        total_silence += float(match.group(1))

    silence_ratio = total_silence / total_duration
    log.info(
        "silence detection complete",
        path=str(audio_path),
        silence_ratio=round(silence_ratio, 3),
        threshold=threshold_ratio,
    )
    return silence_ratio > threshold_ratio


class HttpLectureDownloader:
    """Downloads lecture media tracks over HTTP with resume support."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def download_track(self, url: str, dest: Path) -> AsyncIterator[DownloadProgressEvent]:
        """Stream *url* to *dest*, yielding progress events.

        Supports resume: if *dest* already exists, sends a ``Range`` header
        so only the remaining bytes are fetched.
        """
        existing = dest.stat().st_size if dest.exists() and dest.stat().st_size > 0 else 0
        headers: dict[str, str] = {}
        if existing:
            headers["range"] = f"bytes={existing}-"

        async with self._http.stream("GET", url, headers=headers) as resp:
            status = resp.status_code
            if status == 416:  # noqa: PLR2004
                # Already complete
                return

            if status not in {200, 206}:
                raise LectureDownloadError(f"HTTP {status} downloading {url}")

            mode = "ab" if status == 206 else "wb"  # noqa: PLR2004
            total_header = resp.headers.get("content-length")
            total_bytes = int(total_header) + existing if total_header else None
            downloaded = existing

            start = time.monotonic()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open(mode) as fh:
                async for chunk in resp.aiter_bytes(chunk_size=_CHUNK_SIZE):
                    fh.write(chunk)
                    downloaded += len(chunk)
                    elapsed = time.monotonic() - start
                    speed = (downloaded - existing) / elapsed if elapsed > 0 else 0.0
                    yield DownloadProgressEvent(
                        bytes_downloaded=downloaded,
                        total_bytes=total_bytes,
                        speed_bps=speed,
                    )
