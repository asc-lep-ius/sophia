"""Tests for reliability improvements — subprocess timeouts, enrichment fault-tolerance."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sophia.adapters.lecture_downloader import (
    detect_silence,
    extract_audio,
)
from sophia.domain.errors import LectureDownloadError

if TYPE_CHECKING:
    from pathlib import Path


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _hanging_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> MagicMock:
    """Return a mock subprocess whose communicate() never completes."""
    proc = MagicMock()

    async def _hang() -> tuple[bytes, bytes]:
        await asyncio.sleep(9999)
        return stdout, stderr  # pragma: no cover — never reached

    proc.communicate = _hang
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    proc.returncode = returncode
    return proc


# ------------------------------------------------------------------
# extract_audio — ffmpeg timeout
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ffmpeg_timeout_kills_process(tmp_path: Path) -> None:
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"fake")

    proc = _hanging_process()

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
        patch(
            "sophia.adapters.lecture_downloader._FFMPEG_EXTRACT_TIMEOUT_S",
            0.05,
        ),
    ):
        with pytest.raises(LectureDownloadError, match="timed out"):
            await extract_audio(video)

        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()


# ------------------------------------------------------------------
# detect_silence — ffprobe timeout
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ffprobe_timeout(tmp_path: Path) -> None:
    audio = tmp_path / "lecture.m4a"
    audio.write_bytes(b"fake")

    proc = _hanging_process()

    with (
        patch("shutil.which", return_value="/usr/bin/ffprobe"),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
        patch("sophia.adapters.lecture_downloader._FFPROBE_TIMEOUT_S", 0.05),
    ):
        result = await detect_silence(audio)

    # detect_silence fails open — returns False, does not raise
    assert result is False
    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()


# ------------------------------------------------------------------
# detect_silence — ffmpeg silencedetect timeout
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ffmpeg_silence_timeout(tmp_path: Path) -> None:
    """When ffprobe succeeds but silencedetect hangs, process is killed and result is False."""
    audio = tmp_path / "lecture.m4a"
    audio.write_bytes(b"fake")

    # ffprobe succeeds fast
    probe_proc = MagicMock()
    probe_proc.communicate = AsyncMock(return_value=(b"120.0\n", b""))
    probe_proc.returncode = 0

    # silencedetect hangs
    silence_proc = _hanging_process()

    call_count = 0

    async def _fake_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return probe_proc if call_count == 1 else silence_proc

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        patch("sophia.adapters.lecture_downloader._FFMPEG_SILENCE_TIMEOUT_S", 0.05),
    ):
        result = await detect_silence(audio)

    assert result is False
    silence_proc.kill.assert_called_once()
    silence_proc.wait.assert_awaited_once()


# ------------------------------------------------------------------
# Moodle enrichment — partial results on timeout
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrichment_partial_results() -> None:
    from sophia.adapters.moodle import MoodleAdapter
    from sophia.domain.models import ModuleInfo

    fast_module = ModuleInfo(id=1, name="fast", modname="resource", url="http://example.com/1")
    slow_module = ModuleInfo(id=2, name="slow", modname="resource", url="http://example.com/2")

    async def _fast_enrich(module: ModuleInfo) -> ModuleInfo:
        return module.model_copy(update={"description": "enriched"})

    async def _slow_enrich(module: ModuleInfo) -> ModuleInfo:
        await asyncio.sleep(9999)
        return module  # pragma: no cover — never reached

    adapter = MoodleAdapter.__new__(MoodleAdapter)

    call_count = 0

    async def _enrich_side_effect(module: ModuleInfo) -> ModuleInfo:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return await _fast_enrich(module)
        return await _slow_enrich(module)

    with (
        patch.object(adapter, "_enrich_resource_module", side_effect=_enrich_side_effect),
        patch(
            "sophia.adapters.moodle._ENRICHMENT_TIMEOUT_S",
            0.05,
        ),
    ):
        result = await adapter._enrich_resource_modules([fast_module, slow_module])

    # At least the fast module should be in the results
    assert len(result) >= 1
    assert any(m.description == "enriched" for m in result)


@pytest.mark.asyncio
async def test_enrichment_all_fail_gracefully() -> None:
    from sophia.adapters.moodle import MoodleAdapter
    from sophia.domain.models import ModuleInfo

    module_a = ModuleInfo(id=1, name="a", modname="resource", url="http://example.com/1")
    module_b = ModuleInfo(id=2, name="b", modname="resource", url="http://example.com/2")

    async def _failing_enrich(module: ModuleInfo) -> ModuleInfo:
        raise RuntimeError("boom")

    adapter = MoodleAdapter.__new__(MoodleAdapter)

    with patch.object(adapter, "_enrich_resource_module", side_effect=_failing_enrich):
        result = await adapter._enrich_resource_modules([module_a, module_b])

    # All failures → original modules returned as fallback
    assert len(result) == 2
    # Originals should be returned unchanged
    assert result[0].id == 1
    assert result[1].id == 2
