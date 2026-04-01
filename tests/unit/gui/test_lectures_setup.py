"""Tests for the Hermes setup wizard — pure helper functions."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sophia.domain.models import (
    ComputeDevice,
    ComputeType,
    EmbeddingProvider,
    HermesConfig,
    HermesEmbeddingConfig,
    HermesLLMConfig,
    HermesWhisperConfig,
    LLMProvider,
    WhisperModel,
)
from sophia.gui.pages.lectures_setup import (
    _apply_model_override,
    build_config_summary,
    estimate_storage_mb,
    format_gpu_info,
    is_docker,
)
from sophia.services.hermes_setup import recommend_config


class TestIsDocker:
    """Detect Docker container environment."""

    def test_true_when_dockerenv_exists(self) -> None:
        with (
            patch("sophia.gui.pages.lectures_setup.os.path.exists", return_value=True),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert is_docker() is True

    def test_true_when_env_var_set(self) -> None:
        with (
            patch("sophia.gui.pages.lectures_setup.os.path.exists", return_value=False),
            patch.dict("os.environ", {"SOPHIA_DOCKER": "1"}),
        ):
            assert is_docker() is True

    def test_false_when_neither(self) -> None:
        with (
            patch("sophia.gui.pages.lectures_setup.os.path.exists", return_value=False),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert is_docker() is False


class TestEstimateStorageMb:
    """Storage estimates per Whisper model size."""

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            (WhisperModel.LARGE_V3, 3500),
            (WhisperModel.TURBO, 2000),
            (WhisperModel.MEDIUM, 2000),
            (WhisperModel.SMALL, 1000),
        ],
    )
    def test_known_models(self, model: WhisperModel, expected: int) -> None:
        assert estimate_storage_mb(model) == expected


class TestFormatGpuInfo:
    """Human-readable GPU detection summary."""

    def test_gpu_present_with_vram(self) -> None:
        result = format_gpu_info(has_gpu=True, gpu_name="NVIDIA RTX 3070", vram_mb=8192)
        assert result == "NVIDIA RTX 3070 — 8192 MB VRAM"

    def test_no_gpu(self) -> None:
        result = format_gpu_info(has_gpu=False, gpu_name="", vram_mb=0)
        assert result == "No GPU detected — CPU mode"

    def test_gpu_present_zero_vram(self) -> None:
        result = format_gpu_info(has_gpu=True, gpu_name="NVIDIA GTX 1060", vram_mb=0)
        assert result == "NVIDIA GTX 1060"

    def test_gpu_present_with_different_vram(self) -> None:
        result = format_gpu_info(has_gpu=True, gpu_name="NVIDIA A100", vram_mb=40960)
        assert result == "NVIDIA A100 — 40960 MB VRAM"


class TestBuildConfigSummary:
    """Config summary lines for display."""

    def test_default_config(self) -> None:
        config = HermesConfig()
        lines = build_config_summary(config)
        assert len(lines) == 5
        assert lines[0] == "Whisper model: large-v3"
        assert lines[1] == "Device: cpu"
        assert lines[2] == "Compute type: float32"
        assert lines[3] == "LLM provider: github (openai/gpt-4o)"
        assert lines[4] == "Embedding model: intfloat/multilingual-e5-large"

    def test_custom_config(self) -> None:
        config = HermesConfig(
            whisper=HermesWhisperConfig(
                model=WhisperModel.TURBO,
                device=ComputeDevice.CUDA,
                compute_type=ComputeType.FLOAT16,
            ),
            llm=HermesLLMConfig(
                provider=LLMProvider.OLLAMA,
                model="llama3.2",
                api_key_env="",
            ),
            embeddings=HermesEmbeddingConfig(
                provider=EmbeddingProvider.LOCAL,
                model="nomic-embed-text",
            ),
        )
        lines = build_config_summary(config)
        assert "Whisper model: turbo" in lines
        assert "Device: cuda" in lines
        assert "LLM provider: ollama (llama3.2)" in lines
        assert "Embedding model: nomic-embed-text" in lines


class TestApplyModelOverride:
    """Override Whisper model while preserving rest of config."""

    def test_with_gpu_preserves_device(self) -> None:
        base = recommend_config(True, 8000)
        result = _apply_model_override(base, WhisperModel.MEDIUM, has_gpu=True)
        assert result.whisper.model == WhisperModel.MEDIUM
        assert result.whisper.device == ComputeDevice.CUDA
        assert result.whisper.compute_type == ComputeType.FLOAT16

    def test_without_gpu_forces_cpu(self) -> None:
        base = recommend_config(True, 8000)
        result = _apply_model_override(base, WhisperModel.SMALL, has_gpu=False)
        assert result.whisper.model == WhisperModel.SMALL
        assert result.whisper.device == ComputeDevice.CPU
        assert result.whisper.compute_type == ComputeType.FLOAT32

    def test_preserves_llm_and_embeddings(self) -> None:
        base = recommend_config(False, 0)
        result = _apply_model_override(base, WhisperModel.LARGE_V3, has_gpu=False)
        assert result.llm == base.llm
        assert result.embeddings == base.embeddings
