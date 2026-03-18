"""Tests for reliability improvements — subprocess timeouts, enrichment fault-tolerance."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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


# ------------------------------------------------------------------
# Model & resource caching — embedder and store singletons
# ------------------------------------------------------------------


class TestEmbedderCaching:
    """Verify SentenceTransformerEmbedder is created once and reused."""

    def setup_method(self) -> None:
        from sophia.services import athena_study

        athena_study._embedder_cache = None

    def teardown_method(self) -> None:
        from sophia.services import athena_study

        athena_study._embedder_cache = None

    def test_embedder_cached_across_calls(self) -> None:
        from sophia.services.athena_study import _get_or_create_embedder

        fake_config = MagicMock()

        with patch("sophia.adapters.embedder.SentenceTransformerEmbedder") as mock_cls:
            mock_cls.return_value = MagicMock(name="embedder_instance")

            first = _get_or_create_embedder(fake_config)
            second = _get_or_create_embedder(fake_config)

        assert first is second
        mock_cls.assert_called_once()

    def test_embedder_cache_reset(self) -> None:
        from sophia.services import athena_study
        from sophia.services.athena_study import _get_or_create_embedder

        fake_config = MagicMock()

        with patch("sophia.adapters.embedder.SentenceTransformerEmbedder") as mock_cls:
            mock_cls.return_value = MagicMock(name="instance_a")
            first = _get_or_create_embedder(fake_config)

            # Reset cache
            athena_study._embedder_cache = None

            mock_cls.return_value = MagicMock(name="instance_b")
            after_reset = _get_or_create_embedder(fake_config)

        assert first is not after_reset
        assert mock_cls.call_count == 2


class TestStoreCaching:
    """Verify ChromaKnowledgeStore is created once and reused."""

    def setup_method(self) -> None:
        from sophia.services import athena_study

        athena_study._store_cache = None

    def teardown_method(self) -> None:
        from sophia.services import athena_study

        athena_study._store_cache = None

    def test_store_cached_across_calls(self) -> None:
        from sophia.services.athena_study import _get_or_create_store

        fake_settings = MagicMock()

        with patch("sophia.adapters.knowledge_store.ChromaKnowledgeStore") as mock_cls:
            mock_cls.return_value = MagicMock(name="store_instance")

            first = _get_or_create_store(fake_settings)
            second = _get_or_create_store(fake_settings)

        assert first is second
        mock_cls.assert_called_once()

    def test_store_cache_reset(self) -> None:
        from sophia.services import athena_study
        from sophia.services.athena_study import _get_or_create_store

        fake_settings = MagicMock()

        with patch("sophia.adapters.knowledge_store.ChromaKnowledgeStore") as mock_cls:
            mock_cls.return_value = MagicMock(name="store_a")
            first = _get_or_create_store(fake_settings)

            athena_study._store_cache = None

            mock_cls.return_value = MagicMock(name="store_b")
            after_reset = _get_or_create_store(fake_settings)

        assert first is not after_reset
        assert mock_cls.call_count == 2


# ------------------------------------------------------------------
# Helpers — async context manager wrapper
# ------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _async_cm(obj):
    """Wrap an object in a trivial async context manager."""
    yield obj


# ------------------------------------------------------------------
# SSO auth retry — tenacity on transient failures
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sso_retry_on_transient_503() -> None:
    """_initiate_sso retries once on 503, succeeds on second attempt."""
    from sophia.adapters.auth import _initiate_sso

    ok_response = MagicMock(spec=httpx.Response)
    ok_response.status_code = 200
    ok_response.raise_for_status = MagicMock()
    ok_response.text = "<html></html>"

    error_response = MagicMock(spec=httpx.Response)
    error_response.status_code = 503
    error_response.headers = {}

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(
        side_effect=[
            httpx.HTTPStatusError("503", request=MagicMock(), response=error_response),
            ok_response,
        ]
    )

    result = await _initiate_sso(client, "https://tuwel.tuwien.ac.at")
    assert result is ok_response
    assert client.get.call_count == 2


@pytest.mark.asyncio
async def test_sso_retry_on_transport_error() -> None:
    """_initiate_sso retries on httpx.TransportError."""
    from sophia.adapters.auth import _initiate_sso

    ok_response = MagicMock(spec=httpx.Response)
    ok_response.status_code = 200
    ok_response.raise_for_status = MagicMock()
    ok_response.text = "<html></html>"

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(
        side_effect=[
            httpx.ConnectError("connection reset"),
            ok_response,
        ]
    )

    result = await _initiate_sso(client, "https://tuwel.tuwien.ac.at")
    assert result is ok_response
    assert client.get.call_count == 2


# ------------------------------------------------------------------
# DI container init — timeout on hang
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_app_timeout() -> None:
    """create_app raises RuntimeError if initialization hangs past timeout."""
    from sophia.adapters.auth import SessionCredentials
    from sophia.infra.di import create_app

    fake_creds = SessionCredentials(
        moodle_session="abc",
        sesskey="xyz",
        host="https://tuwel.tuwien.ac.at",
        created_at="2025-01-01T00:00:00+00:00",
    )

    async def _hanging_db(*args, **kwargs):
        await asyncio.sleep(9999)

    mock_http = _async_cm(AsyncMock(spec=httpx.AsyncClient))
    with (
        patch("sophia.infra.di.load_session", return_value=fake_creds),
        patch("sophia.infra.di.http_session", return_value=mock_http),
        patch("sophia.infra.di.connect_db", side_effect=_hanging_db),
        patch("sophia.infra.di._DI_INIT_TIMEOUT_S", 0.05),
        pytest.raises(RuntimeError, match="startup timed out"),
    ):
        async with create_app():
            pass  # pragma: no cover


# ------------------------------------------------------------------
# Whisper transcription — timeout on hang
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcription_timeout() -> None:
    """_transcribe_episode marks episode as failed when Whisper hangs past timeout."""
    from pathlib import Path

    from sophia.services.hermes_transcribe import _transcribe_episode

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    transcriber = MagicMock()
    transcriber.transcribe = lambda _path: time.sleep(10)  # blocks, but not forever

    with patch("sophia.services.hermes_transcribe._TRANSCRIPTION_TIMEOUT_S", 0.05):
        result = await _transcribe_episode(
            db,
            transcriber,
            episode_id="ep-hang",
            module_id=42,
            title="Hanging Lecture",
            audio_path=Path("/tmp/fake.m4a"),
        )

    assert result.status == "failed"
    assert "timed out" in result.error
