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
