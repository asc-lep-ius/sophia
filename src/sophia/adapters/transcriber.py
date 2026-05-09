"""Whisper transcription adapter — wraps faster-whisper with VAD and hallucination filtering.

Implements the ``Transcriber`` protocol.  faster-whisper is an optional
dependency; a clear ``TranscriptionError`` is raised if it is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.errors import TranscriptionError
from sophia.domain.models import TranscriptSegment

if TYPE_CHECKING:
    from pathlib import Path

    from sophia.domain.models import HermesWhisperConfig

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Hallucination filter
# ---------------------------------------------------------------------------

_GERMAN_HALLUCINATIONS: frozenset[str] = frozenset(
    {
        "vielen dank für's zuschauen",
        "untertitelung des zdf",
        "untertitel von stephanie geiges",
        "untertitel der amara.org-community",
        "copyright wdr",
        "swr 2020",
        "mehr informationen auf www.",
        "bis zum nächsten mal.",
        "tschüss!",
        "danke fürs zuschauen!",
        "danke für's zuschauen!",
    }
)

_HALLUCINATION_SILENCE_THRESHOLD = 2.0
_NO_SPEECH_PROB_THRESHOLD = 0.6
_AVG_LOGPROB_THRESHOLD = -1.0
_MIN_TEXT_LENGTH = 3


def is_hallucination(text: str, *, no_speech_prob: float, avg_logprob: float) -> bool:
    """Return True if a transcript segment looks like a Whisper hallucination."""
    stripped = text.strip()
    if len(stripped) < _MIN_TEXT_LENGTH:
        return True
    if stripped.lower() in _GERMAN_HALLUCINATIONS:
        return True
    return no_speech_prob > _NO_SPEECH_PROB_THRESHOLD and avg_logprob < _AVG_LOGPROB_THRESHOLD


# ---------------------------------------------------------------------------
# SRT generation
# ---------------------------------------------------------------------------


def _format_srt_time(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS,mmm`` for SRT files."""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list[TranscriptSegment]) -> str:
    """Convert transcript segments to SRT subtitle format."""
    if not segments:
        return ""
    lines: list[str] = []
    for idx, seg in enumerate(segments, start=1):
        lines.append(str(idx))
        lines.append(f"{_format_srt_time(seg.start)} --> {_format_srt_time(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# WhisperTranscriber
# ---------------------------------------------------------------------------


class WhisperTranscriber:
    """Transcriber backed by faster-whisper with hallucination filtering."""

    def __init__(self, config: HermesWhisperConfig, model_dir: Path | None = None) -> None:
        self._config = config
        self._model_dir = model_dir
        self._model: Any = None

    def _ensure_model(self) -> Any:
        """Lazy-load the WhisperModel on first use."""
        if self._model is not None:
            return self._model  # pyright: ignore[reportUnknownVariableType]
        try:
            from faster_whisper import WhisperModel as FWModel  # type: ignore[import-not-found]
        except ImportError:
            raise TranscriptionError(
                "faster-whisper not installed — run: uv pip install sophia[hermes]"
            ) from None

        # Resolve compute type — fall back if the requested type is unsupported
        compute_type = self._resolve_compute_type(self._config.device, self._config.compute_type)

        log.info(
            "loading_whisper_model",
            model=self._config.model,
            device=self._config.device,
            compute_type=compute_type,
        )
        self._model = FWModel(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            self._config.model,
            device=self._config.device,
            compute_type=compute_type,
            download_root=str(self._model_dir) if self._model_dir else None,
        )
        return self._model  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    def _resolve_compute_type(self, device: str, requested: str) -> str:
        """Return a supported compute type, falling back if requested is unavailable.

        Queries CTranslate2 at runtime for supported types on the target device.
        Falls back to efficient alternatives when the requested type is unsupported.
        """
        try:
            import ctranslate2  # type: ignore[import-not-found]
        except ImportError:
            # CTranslate2 unavailable — let faster-whisper handle it
            return requested

        try:
            supported: set[str] = set(
                ctranslate2.get_supported_compute_types(device)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            )
        except Exception:
            # If query fails, proceed with the requested type
            log.warning(
                "compute_type_query_failed",
                device=device,
                requested=requested,
                fallback=requested,
            )
            return requested

        if requested in supported:
            return requested

        # Choose a fallback based on device and what's available
        if device == "cuda":
            # Prefer int8 or int8_float32 for GPU efficiency, then float32
            for fallback in ("int8", "int8_float32", "float32"):
                if fallback in supported:
                    log.warning(
                        "compute_type_fallback",
                        device=device,
                        requested=requested,
                        fallback=fallback,
                        supported=sorted(supported),
                    )
                    return fallback
        else:
            # CPU fallback priority: int8 > int16 > float32
            for fallback in ("int8", "int16", "float32"):
                if fallback in supported:
                    log.warning(
                        "compute_type_fallback",
                        device=device,
                        requested=requested,
                        fallback=fallback,
                        supported=sorted(supported),
                    )
                    return fallback

        # No suitable fallback found — return requested and let faster-whisper fail
        log.warning(
            "no_compute_type_fallback",
            device=device,
            requested=requested,
            supported=sorted(supported),
        )
        return requested

    def transcribe(
        self,
        audio_path: Path,
        *,
        on_progress: Any = None,
    ) -> list[TranscriptSegment]:
        """Transcribe an audio file, filtering hallucinations and duplicates.

        Args:
            audio_path: Path to the audio file to transcribe.
            on_progress: Optional callback invoked during segment generation.
                         Signature: (current: int, total: int) -> None.
                         Current is processed seconds; total is duration if
                         known, else segment count.
        """
        model: Any = self._ensure_model()
        try:
            segments_iter, _info = model.transcribe(
                str(audio_path),
                language=self._config.language,
                vad_filter=self._config.vad_filter,
                word_timestamps=False,
                hallucination_silence_threshold=_HALLUCINATION_SILENCE_THRESHOLD,
            )
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(str(exc)) from exc

        # Determine duration for progress if available
        total_duration: float | None = None
        if hasattr(_info, "duration"):
            try:
                total_duration = float(_info.duration)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                if total_duration <= 0:
                    total_duration = None
            except (TypeError, ValueError):
                total_duration = None

        result: list[TranscriptSegment] = []
        prev_text: str | None = None
        raw_count = 0

        # Consume the generator incrementally — this is where the slow transcription happens
        for seg in segments_iter:
            raw_count += 1
            text = seg.text.strip()

            # Filter hallucinations
            if is_hallucination(
                text, no_speech_prob=seg.no_speech_prob, avg_logprob=seg.avg_logprob
            ):
                continue

            # Filter duplicates
            if text == prev_text:
                continue

            result.append(TranscriptSegment(start=seg.start, end=seg.end, text=text))
            prev_text = text

            # Fire progress callback during generator consumption
            if on_progress:
                if total_duration is not None and total_duration > 0:
                    # Use timestamp vs duration for honest progress
                    current_seconds = int(seg.end)
                    total_seconds = int(total_duration)
                    on_progress(current_seconds, total_seconds)
                else:
                    # Fallback: report segment count with moving estimate
                    # Use raw_count + 5 as denominator to avoid premature 100%
                    on_progress(raw_count, raw_count + 5)

        # Final progress report with accurate count
        if on_progress and result:
            if total_duration is not None and total_duration > 0:
                total_seconds = int(total_duration)
                on_progress(total_seconds, total_seconds)
            else:
                on_progress(raw_count, raw_count)

        dropped = raw_count - len(result)
        log.info("transcription_filtered", path=str(audio_path), kept=len(result), dropped=dropped)
        return result
