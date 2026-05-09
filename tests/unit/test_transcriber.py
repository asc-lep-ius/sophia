"""Tests for WhisperTranscriber — hallucination filtering, SRT, transcription."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from sophia.adapters.transcriber import (
    WhisperTranscriber,
    _format_srt_time,  # pyright: ignore[reportPrivateUsage]
    is_hallucination,
    segments_to_srt,
)
from sophia.domain.errors import TranscriptionError
from sophia.domain.models import HermesWhisperConfig, TranscriptSegment

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockSegment:
    """Mimics a faster-whisper Segment namedtuple."""

    def __init__(
        self,
        start: float,
        end: float,
        text: str,
        no_speech_prob: float = 0.1,
        avg_logprob: float = -0.3,
    ):
        self.start = start
        self.end = end
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob


# ---------------------------------------------------------------------------
# is_hallucination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Vielen Dank für's Zuschauen",
        "Untertitelung des ZDF",
        "Untertitel von Stephanie Geiges",
        "Copyright WDR",
    ],
)
def test_is_hallucination_known_string(text: str) -> None:
    assert is_hallucination(text, no_speech_prob=0.1, avg_logprob=-0.3) is True


def test_is_hallucination_case_insensitive() -> None:
    assert (
        is_hallucination("VIELEN DANK FÜR'S ZUSCHAUEN", no_speech_prob=0.1, avg_logprob=-0.3)
        is True
    )


def test_is_hallucination_normal_text() -> None:
    assert (
        is_hallucination("Heute behandeln wir Analysis", no_speech_prob=0.1, avg_logprob=-0.3)
        is False
    )


def test_is_hallucination_low_quality() -> None:
    assert is_hallucination("some noise", no_speech_prob=0.7, avg_logprob=-1.5) is True


def test_is_hallucination_short_text() -> None:
    assert is_hallucination("ab", no_speech_prob=0.1, avg_logprob=-0.3) is True


def test_is_hallucination_empty() -> None:
    assert is_hallucination("", no_speech_prob=0.1, avg_logprob=-0.3) is True


def test_is_hallucination_whitespace_stripped() -> None:
    assert is_hallucination("  Tschüss!  ", no_speech_prob=0.1, avg_logprob=-0.3) is True


# ---------------------------------------------------------------------------
# SRT generation
# ---------------------------------------------------------------------------


def test_segments_to_srt_basic() -> None:
    segments = [
        TranscriptSegment(start=0.0, end=2.5, text="Hallo zusammen."),
        TranscriptSegment(start=3.0, end=5.0, text="Heute geht es um Mathe."),
    ]
    srt = segments_to_srt(segments)
    assert "1\n00:00:00,000 --> 00:00:02,500\nHallo zusammen.\n" in srt
    assert "2\n00:00:03,000 --> 00:00:05,000\nHeute geht es um Mathe.\n" in srt


def test_segments_to_srt_empty() -> None:
    assert segments_to_srt([]) == ""


def test_format_srt_time_zero() -> None:
    assert _format_srt_time(0.0) == "00:00:00,000"


def test_format_srt_time_complex() -> None:
    assert _format_srt_time(3661.5) == "01:01:01,500"


# ---------------------------------------------------------------------------
# WhisperTranscriber — filters hallucinations
# ---------------------------------------------------------------------------


def _make_transcriber(mock_model: MagicMock) -> WhisperTranscriber:
    config = HermesWhisperConfig()
    transcriber = WhisperTranscriber(config)
    transcriber._model = mock_model  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    return transcriber


def test_transcriber_filters_hallucinations(tmp_path: Path) -> None:
    audio = tmp_path / "lecture.mp3"
    audio.touch()

    segments = [
        MockSegment(0.0, 5.0, "Willkommen zur Vorlesung."),
        MockSegment(5.0, 10.0, "Vielen Dank für's Zuschauen"),
        MockSegment(10.0, 15.0, "Wir beginnen mit Kapitel 1."),
    ]

    mock_model = MagicMock()
    mock_info = MagicMock()
    mock_model.transcribe.return_value = (iter(segments), mock_info)

    transcriber = _make_transcriber(mock_model)
    result = transcriber.transcribe(audio)

    assert len(result) == 2
    assert result[0].text == "Willkommen zur Vorlesung."
    assert result[1].text == "Wir beginnen mit Kapitel 1."


def test_transcriber_filters_duplicates(tmp_path: Path) -> None:
    audio = tmp_path / "lecture.mp3"
    audio.touch()

    segments = [
        MockSegment(0.0, 5.0, "Erster Satz."),
        MockSegment(5.0, 10.0, "Erster Satz."),
        MockSegment(10.0, 15.0, "Zweiter Satz."),
    ]

    mock_model = MagicMock()
    mock_info = MagicMock()
    mock_model.transcribe.return_value = (iter(segments), mock_info)

    transcriber = _make_transcriber(mock_model)
    result = transcriber.transcribe(audio)

    assert len(result) == 2
    assert result[0].text == "Erster Satz."
    assert result[1].text == "Zweiter Satz."


def test_transcriber_import_error(tmp_path: Path) -> None:
    import sys
    from unittest.mock import patch

    audio = tmp_path / "lecture.mp3"
    audio.touch()

    config = HermesWhisperConfig()
    transcriber = WhisperTranscriber(config)

    with (
        patch.dict(sys.modules, {"faster_whisper": None}),
        pytest.raises(TranscriptionError, match="faster-whisper not installed"),
    ):
        transcriber.transcribe(audio)


def test_transcriber_wraps_exceptions(tmp_path: Path) -> None:
    audio = tmp_path / "lecture.mp3"
    audio.touch()

    mock_model = MagicMock()
    mock_model.transcribe.side_effect = RuntimeError("GPU out of memory")

    transcriber = _make_transcriber(mock_model)

    with pytest.raises(TranscriptionError, match="GPU out of memory"):
        transcriber.transcribe(audio)


def test_transcriber_invokes_progress_callback(tmp_path: Path) -> None:
    """Verify that progress callbacks fire DURING generator consumption, not after.

    This test uses a generator that records yield events, allowing us to verify
    that callbacks are invoked interleaved with segment generation (the real slow path).
    """
    audio = tmp_path / "lecture.mp3"
    audio.touch()

    events: list[str] = []

    def fake_segment_generator():
        """Generator that records when it yields each segment."""
        for i in range(3):
            events.append(f"yield_{i}")
            yield MockSegment(i * 5.0, (i + 1) * 5.0, f"Segment {i}.")

    mock_model = MagicMock()
    mock_info = MagicMock()
    mock_info.duration = 15.0  # 3 segments × 5 seconds
    mock_model.transcribe.return_value = (fake_segment_generator(), mock_info)

    transcriber = _make_transcriber(mock_model)

    progress_calls: list[tuple[int, int]] = []

    def on_progress(current: int, total: int) -> None:
        events.append(f"progress_{current}_{total}")
        progress_calls.append((current, total))

    result = transcriber.transcribe(audio, on_progress=on_progress)

    # Should have 3 segments after filtering
    assert len(result) == 3

    # Progress callback should have been invoked during iteration
    assert len(progress_calls) > 0

    # Critical assertion: verify callbacks fired DURING generator consumption
    # Events should alternate: yield_0, progress_X_Y, yield_1, progress_X_Y, ...
    # Find first yield and first progress — progress must come after at least one yield
    first_yield_idx = next(i for i, e in enumerate(events) if e.startswith("yield_"))
    first_progress_idx = next(i for i, e in enumerate(events) if e.startswith("progress_"))

    # Progress must fire after yields start, proving it happens during consumption
    assert first_progress_idx > first_yield_idx, (
        f"Progress fired at {first_progress_idx} before/during first yield at {first_yield_idx}. "
        f"Events: {events}"
    )

    # Verify we see interleaving: at least one yield before last progress
    last_progress_idx = (
        len(events)
        - 1
        - events[::-1].index(next(e for e in reversed(events) if e.startswith("progress_")))
    )
    last_yield_idx = (
        len(events)
        - 1
        - events[::-1].index(next(e for e in reversed(events) if e.startswith("yield_")))
    )

    # Last yield should come before or around the same time as last progress
    assert last_yield_idx <= last_progress_idx + 1, (
        f"Generator materialization may have happened before callbacks. Events: {events}"
    )

    # Verify progress uses duration-based reporting (seconds vs total seconds)
    # With 15s duration and segments at 5s, 10s, 15s, we expect current ≈ timestamps
    assert any(0 < current < 15 for current, _ in progress_calls[:-1]), (
        f"Expected intermediate progress < 15s, got {progress_calls}"
    )
    # Final progress should be (15, 15) or close
    assert progress_calls[-1][0] == 15 and progress_calls[-1][1] == 15


def test_transcriber_progress_fallback_no_duration(tmp_path: Path) -> None:
    """When duration is unavailable, progress uses segment count with moving estimate."""
    audio = tmp_path / "lecture.mp3"
    audio.touch()

    segments = [
        MockSegment(0.0, 5.0, "First segment."),
        MockSegment(5.0, 10.0, "Second segment."),
        MockSegment(10.0, 15.0, "Third segment."),
    ]

    mock_model = MagicMock()
    mock_info = MagicMock(spec=[])  # Empty spec means no attributes
    mock_model.transcribe.return_value = (iter(segments), mock_info)

    transcriber = _make_transcriber(mock_model)

    progress_calls: list[tuple[int, int]] = []

    def on_progress(current: int, total: int) -> None:
        progress_calls.append((current, total))

    result = transcriber.transcribe(audio, on_progress=on_progress)

    assert len(result) == 3
    assert len(progress_calls) > 0

    # Without duration, fallback uses raw_count with moving estimate
    # Intermediate calls should show current < total (not 100%)
    intermediate_calls = progress_calls[:-1]
    assert all(current < total for current, total in intermediate_calls), (
        f"Expected all intermediate progress < 100%, got {intermediate_calls}"
    )

    # Final call should be (3, 3) since we have 3 raw segments
    assert progress_calls[-1] == (3, 3)


# ---------------------------------------------------------------------------
# Compute type fallback
# ---------------------------------------------------------------------------


def test_resolve_compute_type_fallback_cuda_float16_to_int8() -> None:
    """When float16 is unsupported on CUDA, fall back to int8."""
    from unittest.mock import MagicMock, patch

    from sophia.domain.models import ComputeDevice, ComputeType

    config = HermesWhisperConfig(device=ComputeDevice.CUDA, compute_type=ComputeType.FLOAT16)
    transcriber = WhisperTranscriber(config)

    mock_ct2 = MagicMock()
    mock_ct2.get_supported_compute_types.return_value = ["float32", "int8", "int8_float32"]

    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}):
        resolved = transcriber._resolve_compute_type("cuda", "float16")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert resolved == "int8"


def test_resolve_compute_type_supported_remains() -> None:
    """When the requested compute type is supported, it's used as-is."""
    from unittest.mock import MagicMock, patch

    from sophia.domain.models import ComputeDevice, ComputeType

    config = HermesWhisperConfig(device=ComputeDevice.CUDA, compute_type=ComputeType.FLOAT16)
    transcriber = WhisperTranscriber(config)

    mock_ct2 = MagicMock()
    mock_ct2.get_supported_compute_types.return_value = ["float16", "float32", "int8"]

    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}):
        resolved = transcriber._resolve_compute_type("cuda", "float16")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert resolved == "float16"


def test_resolve_compute_type_ctranslate2_unavailable() -> None:
    """When ctranslate2 is not installed, return requested type."""
    from unittest.mock import patch

    from sophia.domain.models import ComputeDevice, ComputeType

    config = HermesWhisperConfig(device=ComputeDevice.CUDA, compute_type=ComputeType.FLOAT16)
    transcriber = WhisperTranscriber(config)

    with patch.dict("sys.modules", {"ctranslate2": None}):
        resolved = transcriber._resolve_compute_type("cuda", "float16")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert resolved == "float16"


def test_resolve_compute_type_query_fails() -> None:
    """When supported types query fails, return requested type."""
    from unittest.mock import MagicMock, patch

    from sophia.domain.models import ComputeDevice, ComputeType

    config = HermesWhisperConfig(device=ComputeDevice.CUDA, compute_type=ComputeType.FLOAT16)
    transcriber = WhisperTranscriber(config)

    mock_ct2 = MagicMock()
    mock_ct2.get_supported_compute_types.side_effect = RuntimeError("Device error")

    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}):
        resolved = transcriber._resolve_compute_type("cuda", "float16")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert resolved == "float16"


def test_resolve_compute_type_cpu_fallback() -> None:
    """When float16 is unsupported on CPU, fall back to int8."""
    from unittest.mock import MagicMock, patch

    from sophia.domain.models import ComputeDevice, ComputeType

    config = HermesWhisperConfig(device=ComputeDevice.CPU, compute_type=ComputeType.FLOAT16)
    transcriber = WhisperTranscriber(config)

    mock_ct2 = MagicMock()
    mock_ct2.get_supported_compute_types.return_value = ["float32", "int16", "int8"]

    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}):
        resolved = transcriber._resolve_compute_type("cpu", "float16")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert resolved == "int8"
