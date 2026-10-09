"""Published caption tracks as transcripts — WebVTT parsing, track choice, fetching.

TU Wien's player ships auto-generated captions for most recordings as WebVTT
files on ``cdn.video.tuwien.ac.at``. Reading one costs a 110 KB download
where Whisper costs the audio and a quarter of an hour of GPU, so the pipeline
tries this first. See ``docs/captions-as-transcript.md``.

Implements the ``CaptionFetcher`` protocol. The parser is deliberately
stdlib-only: a WebVTT cue is a timestamp line and the text beneath it, and
the files seen so far use nothing else.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

import httpx
import structlog

from sophia.domain.errors import CaptionError
from sophia.domain.models import LectureCaption, TranscriptSegment
from sophia.infra.http import is_trusted_url

if TYPE_CHECKING:
    from collections.abc import Sequence

log = structlog.get_logger()

# The fork's fallback: a course with no configured language, or one whose
# language has no caption track, reads the German track. TU Wien lectures are
# spoken in German unless the course says otherwise, and the English track is
# a machine translation of the German one.
DEFAULT_CAPTION_LANGUAGE = "de"

_CAPTION_FORMAT = "vtt"
_MAX_CAPTION_BYTES = 20 * 1024**2
_FETCH_TIMEOUT_S = 60.0

# The millisecond field admits a sign: TU Wien's generator writes a cue that
# starts just before the recording as ``00:00:00.-448``, and a lecture is not
# Whisper's for that.
_TIMESTAMP = r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](-?\d{1,3})"
_CUE_TIMING_RE = re.compile(rf"^\s*{_TIMESTAMP}\s*-->\s*{_TIMESTAMP}(?:\s.*)?$")
_TAG_RE = re.compile(r"<[^>]*>")
_BLOCK_KEYWORDS = ("NOTE", "STYLE", "REGION")


def select_caption_track(
    captions: Sequence[LectureCaption],
    preferred_lang: str,
) -> LectureCaption | None:
    """Pick the caption track to read as the transcript, or None for Whisper.

    The course's language wins, German is the fallback, and any other track is
    left alone — a lecture captioned only in a third language is Whisper's.
    """
    vtt_tracks = [c for c in captions if c.format == _CAPTION_FORMAT]
    for wanted in (preferred_lang, DEFAULT_CAPTION_LANGUAGE):
        base = _base_language(wanted)
        for track in vtt_tracks:
            if _base_language(track.lang) == base:
                return track
    return None


def _base_language(tag: str) -> str:
    """``de-AT`` and ``de`` name the same track."""
    return tag.strip().lower().split("-", 1)[0]


def parse_vtt(text: str) -> list[TranscriptSegment]:
    """Turn a WebVTT document into transcript segments with the cue times kept.

    Cue identifiers, settings after the timing, NOTE/STYLE/REGION blocks and
    inline tags such as ``<v Speaker>`` are dropped; the text of a multi-line
    cue is joined with spaces. A cue whose timing cannot be read is skipped
    and counted in one warning, because one bad line in two thousand is not a
    reason to send the lecture to Whisper. Raises ``CaptionError`` only when
    the document is not WebVTT at all.
    """
    body = text.lstrip("\ufeff")
    if not body.startswith("WEBVTT"):
        raise CaptionError("not a WebVTT document")

    segments: list[TranscriptSegment] = []
    malformed: list[str] = []
    for block in re.split(r"\r?\n\r?\n+", body)[1:]:
        lines = block.strip().splitlines()
        if not lines or lines[0].split(maxsplit=1)[0] in _BLOCK_KEYWORDS:
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        timing = _CUE_TIMING_RE.match(lines[timing_index])
        if timing is None:
            malformed.append(lines[timing_index].strip())
            continue
        cue_text = " ".join(
            html.unescape(_TAG_RE.sub("", line)).strip() for line in lines[timing_index + 1 :]
        ).strip()
        if not cue_text:
            continue
        groups = timing.groups()
        start = _to_seconds(groups[:4])
        segments.append(
            TranscriptSegment(start=start, end=max(start, _to_seconds(groups[4:])), text=cue_text)
        )
    if malformed:
        log.warning(
            "captions_cues_dropped",
            dropped=len(malformed),
            kept=len(segments),
            example=malformed[0],
        )
    return segments


def _to_seconds(parts: Sequence[str | None]) -> float:
    """Seconds since the start, clamped at zero for a cue that begins before it."""
    hours, minutes, seconds, millis = (int(part or 0) for part in parts)
    return max(0.0, hours * 3600 + minutes * 60 + seconds + millis / 1000)


class HttpCaptionFetcher:
    """Fetches caption files over the shared HTTP session.

    The URL comes from a scraped TUWEL page, so it is fetched only when it is
    an https URL on a TU Wien host, and the body is read in bounded chunks
    rather than trusted to be small. The CDN serves the files without a
    cookie; the shared client is used for its redirect guard.
    """

    def __init__(self, http: httpx.AsyncClient, max_bytes: int = _MAX_CAPTION_BYTES) -> None:
        self._http = http
        self._max_bytes = max_bytes

    async def fetch_captions(self, url: str) -> str:
        if not is_trusted_url(url):
            raise CaptionError(f"refusing to fetch captions from {url}: not a TU Wien https URL")
        try:
            async with self._http.stream("GET", url, timeout=_FETCH_TIMEOUT_S) as response:
                if not response.is_success:
                    raise CaptionError(f"HTTP {response.status_code} fetching {url}")
                body = await self._read_bounded(response, url)
        except httpx.HTTPError as exc:
            raise CaptionError(f"fetching {url}: {exc}") from exc
        return body.decode("utf-8", errors="replace")

    async def _read_bounded(self, response: httpx.Response, url: str) -> bytes:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_bytes:
            raise CaptionError(f"caption file of {declared} bytes exceeds {self._max_bytes}")
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self._max_bytes:
                raise CaptionError(f"caption file exceeds {self._max_bytes} bytes: {url}")
            chunks.append(chunk)
        return b"".join(chunks)
