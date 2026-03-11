"""Tests for Hermes setup service — hardware detection, config recommendation, and persistence."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

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
from sophia.services.hermes_setup import (
    detect_gpu,
    load_hermes_config,
    recommend_config,
    save_hermes_config,
    validate_llm_provider,
)

if TYPE_CHECKING:
    from pathlib import Path


NVIDIA_SMI_OUTPUT = """\
GPU 0: NVIDIA GeForce RTX 4090 (UUID: GPU-abc123)
  FB Memory Usage: Total: 24564 MiB
"""

NVIDIA_SMI_LOW_VRAM = """\
GPU 0: NVIDIA GeForce GTX 1650 (UUID: GPU-xyz789)
  FB Memory Usage: Total: 4096 MiB
"""


class TestDetectGpu:
    def test_no_nvidia_smi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When nvidia-smi is not found, returns (False, "", 0)."""

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", _raise)
        has_gpu, name, vram = detect_gpu()
        assert has_gpu is False
        assert name == ""
        assert vram == 0

    def test_nvidia_smi_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When nvidia-smi returns valid output, parse GPU name and VRAM."""

        def _fake_run(
            cmd: list[str], *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "-q" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=NVIDIA_SMI_OUTPUT, stderr=""
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="NVIDIA GeForce RTX 4090\n", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", _fake_run)
        has_gpu, name, vram = detect_gpu()
        assert has_gpu is True
        assert name == "NVIDIA GeForce RTX 4090"
        assert vram == 24564

    def test_nvidia_smi_low_vram(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When nvidia-smi reports low VRAM, still detect GPU correctly."""

        def _fake_run(
            cmd: list[str], *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "-q" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=NVIDIA_SMI_LOW_VRAM, stderr=""
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="NVIDIA GeForce GTX 1650\n", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", _fake_run)
        has_gpu, name, vram = detect_gpu()
        assert has_gpu is True
        assert name == "NVIDIA GeForce GTX 1650"
        assert vram == 4096

    def test_nvidia_smi_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When nvidia-smi times out, treat as no GPU."""

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10)

        monkeypatch.setattr(subprocess, "run", _raise)
        has_gpu, name, vram = detect_gpu()
        assert has_gpu is False
        assert name == ""
        assert vram == 0

    def test_nvidia_smi_failure_returncode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When nvidia-smi returns non-zero, treat as no GPU."""

        def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=["nvidia-smi"],
                returncode=1,
                stdout="",
                stderr="NVIDIA-SMI has failed",
            )

        monkeypatch.setattr(subprocess, "run", _fake_run)
        has_gpu, name, vram = detect_gpu()
        assert has_gpu is False
        assert name == ""
        assert vram == 0


class TestRecommendConfig:
    def test_gpu_high_vram(self) -> None:
        """24 GB VRAM → large-v3, cuda, float16."""
        config = recommend_config(has_gpu=True, vram_mb=24564)
        assert config.whisper.model == WhisperModel.LARGE_V3
        assert config.whisper.device == ComputeDevice.CUDA
        assert config.whisper.compute_type == ComputeType.FLOAT16

    def test_gpu_low_vram(self) -> None:
        """4 GB VRAM → turbo, cuda, float16."""
        config = recommend_config(has_gpu=True, vram_mb=4096)
        assert config.whisper.model == WhisperModel.TURBO
        assert config.whisper.device == ComputeDevice.CUDA
        assert config.whisper.compute_type == ComputeType.FLOAT16

    def test_cpu_only(self) -> None:
        """No GPU → small, cpu, float32."""
        config = recommend_config(has_gpu=False, vram_mb=0)
        assert config.whisper.model == WhisperModel.SMALL
        assert config.whisper.device == ComputeDevice.CPU
        assert config.whisper.compute_type == ComputeType.FLOAT32

    @pytest.mark.parametrize(
        ("vram_mb", "expected_model"),
        [
            (8000, WhisperModel.LARGE_V3),
            (7999, WhisperModel.TURBO),
            (4000, WhisperModel.TURBO),
            (3999, WhisperModel.SMALL),
        ],
        ids=["at-high", "below-high", "at-low", "below-low"],
    )
    def test_vram_threshold_boundaries(self, vram_mb: int, expected_model: WhisperModel) -> None:
        """VRAM thresholds select the correct Whisper model at exact boundaries."""
        config = recommend_config(has_gpu=True, vram_mb=vram_mb)
        assert config.whisper.model == expected_model

    def test_default_llm_is_github(self) -> None:
        """Default LLM provider should be GitHub Models."""
        config = recommend_config(has_gpu=False, vram_mb=0)
        assert config.llm.provider == LLMProvider.GITHUB
        assert config.llm.api_key_env == "GITHUB_TOKEN"

    def test_default_embeddings_local(self) -> None:
        """Default embeddings should be local."""
        config = recommend_config(has_gpu=False, vram_mb=0)
        assert config.embeddings.provider == EmbeddingProvider.LOCAL


class TestSaveAndLoadConfig:
    def test_round_trip(self, tmp_path: Path) -> None:
        """Save then load should produce identical config."""
        config = HermesConfig(
            whisper=HermesWhisperConfig(
                model=WhisperModel.LARGE_V3,
                device=ComputeDevice.CUDA,
                compute_type=ComputeType.FLOAT16,
            ),
            llm=HermesLLMConfig(
                provider=LLMProvider.GEMINI,
                model="gemini-2.0-flash",
                api_key_env="SOPHIA_GEMINI_API_KEY",
            ),
            embeddings=HermesEmbeddingConfig(
                provider=EmbeddingProvider.GITHUB,
                model="openai/text-embedding-3-small",
            ),
        )
        save_hermes_config(config, tmp_path)
        loaded = load_hermes_config(tmp_path)
        assert loaded == config

    def test_load_missing(self, tmp_path: Path) -> None:
        """Loading from a directory with no hermes.toml returns None."""
        assert load_hermes_config(tmp_path) is None

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """Save should create the config directory if it doesn't exist."""
        config_dir = tmp_path / "nested" / "config"
        save_hermes_config(HermesConfig(), config_dir)
        assert (config_dir / "hermes.toml").exists()


class TestValidateLlmProvider:
    def test_github_with_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GitHub provider with GITHUB_TOKEN set → valid."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        config = HermesLLMConfig(
            provider=LLMProvider.GITHUB,
            model="openai/gpt-4o",
            api_key_env="GITHUB_TOKEN",
        )
        valid, msg = validate_llm_provider(config)
        assert valid is True
        assert "GITHUB_TOKEN" in msg

    def test_github_missing_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GitHub provider without GITHUB_TOKEN → invalid."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        config = HermesLLMConfig(
            provider=LLMProvider.GITHUB,
            model="openai/gpt-4o",
            api_key_env="GITHUB_TOKEN",
        )
        valid, msg = validate_llm_provider(config)
        assert valid is False
        assert "GITHUB_TOKEN" in msg

    def test_ollama_no_key_needed(self) -> None:
        """Ollama provider needs no API key."""
        config = HermesLLMConfig(
            provider=LLMProvider.OLLAMA,
            model="llama3.2",
            api_key_env="",
        )
        valid, message = validate_llm_provider(config)
        assert valid is True
        assert "no API key required" in message
