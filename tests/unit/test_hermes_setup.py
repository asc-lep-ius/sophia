"""Tests for Hermes setup service — hardware detection, config recommendation, and persistence."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from sophia.domain.errors import TranscriptionError
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
    detect_gpu_context,
    get_provider_defaults,
    load_hermes_config,
    recommend_compute_type,
    recommend_config,
    save_hermes_config,
    validate_api_key_live,
    validate_llm_provider,
    verify_compute_type,
)

if TYPE_CHECKING:
    from pathlib import Path


# What ctranslate2.get_supported_compute_types("cuda") returns on hephaestus's
# GTX 1070 (compute capability 6.1), and on a card with efficient float16.
PASCAL_CUDA_TYPES = {"float32", "int8", "int8_float32"}
AMPERE_CUDA_TYPES = {"float32", "float16", "int8", "int8_float16", "int8_float32"}


def _fake_ctranslate2(monkeypatch: pytest.MonkeyPatch, cuda_types: set[str]) -> list[str]:
    """Stand in for ctranslate2, whether or not the hermes extra is installed.

    Returns the list of devices it was asked about.
    """
    asked: list[str] = []

    def _get_supported_compute_types(device: str) -> set[str]:
        asked.append(device)
        return set(cuda_types)

    module = SimpleNamespace(get_supported_compute_types=_get_supported_compute_types)
    monkeypatch.setitem(sys.modules, "ctranslate2", module)
    return asked


@pytest.fixture(autouse=True)
def _float16_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test to a GPU that supports float16; tests override it."""
    _fake_ctranslate2(monkeypatch, AMPERE_CUDA_TYPES)


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

    def test_name_query_timeout_graceful(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """VRAM query succeeds but name query times out → GPU detected, empty name."""
        call_count = 0

        def _fake_run(
            cmd: list[str], *_args: object, **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=NVIDIA_SMI_OUTPUT, stderr=""
                )
            raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        has_gpu, name, vram = detect_gpu()
        assert has_gpu is True
        assert name == ""
        assert vram == 24564

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


class TestRecommendComputeType:
    @pytest.mark.parametrize(
        ("cuda_types", "expected"),
        [
            (AMPERE_CUDA_TYPES, ComputeType.FLOAT16),
            ({"float32", "int8", "int8_float16"}, ComputeType.INT8_FLOAT16),
            (PASCAL_CUDA_TYPES, ComputeType.INT8),
            ({"float32"}, ComputeType.FLOAT32),
        ],
        ids=["float16", "int8_float16", "pascal-int8", "float32-only"],
    )
    def test_prefers_fastest_supported(
        self, monkeypatch: pytest.MonkeyPatch, cuda_types: set[str], expected: ComputeType
    ) -> None:
        _fake_ctranslate2(monkeypatch, cuda_types)
        assert recommend_compute_type(ComputeDevice.CUDA) == expected

    def test_cpu_is_float32_without_asking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        asked = _fake_ctranslate2(monkeypatch, PASCAL_CUDA_TYPES)
        assert recommend_compute_type(ComputeDevice.CPU) == ComputeType.FLOAT32
        assert asked == []

    def test_without_ctranslate2_keeps_float16_and_says_so(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "ctranslate2", None)
        with capture_logs() as logs:
            assert recommend_compute_type(ComputeDevice.CUDA) == ComputeType.FLOAT16
        assert [entry["event"] for entry in logs] == ["compute_type_check_skipped"]

    def test_setup_on_pascal_writes_a_supported_type(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Scenario 1: the GTX 1070 gets int8 in hermes.toml, not float16."""
        _fake_ctranslate2(monkeypatch, PASCAL_CUDA_TYPES)
        save_hermes_config(recommend_config(has_gpu=True, vram_mb=8192), tmp_path)
        loaded = load_hermes_config(tmp_path)
        assert loaded is not None
        assert loaded.whisper.compute_type == ComputeType.INT8
        assert 'compute_type = "int8"' in (tmp_path / "hermes.toml").read_text()


class TestVerifyComputeType:
    def test_unsupported_type_names_the_supported_ones(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_ctranslate2(monkeypatch, PASCAL_CUDA_TYPES)
        whisper = HermesWhisperConfig(device=ComputeDevice.CUDA, compute_type=ComputeType.FLOAT16)
        with pytest.raises(TranscriptionError, match="float32, int8, int8_float32"):
            verify_compute_type(whisper)

    def test_supported_type_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_ctranslate2(monkeypatch, PASCAL_CUDA_TYPES)
        verify_compute_type(
            HermesWhisperConfig(device=ComputeDevice.CUDA, compute_type=ComputeType.INT8)
        )

    def test_cpu_is_skipped_out_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        asked = _fake_ctranslate2(monkeypatch, PASCAL_CUDA_TYPES)
        whisper = HermesWhisperConfig(device=ComputeDevice.CPU, compute_type=ComputeType.FLOAT32)
        with capture_logs() as logs:
            verify_compute_type(whisper)
        assert asked == []
        assert logs[0]["event"] == "compute_type_check_skipped"
        assert logs[0]["reason"] == "cpu device"

    def test_missing_ctranslate2_is_skipped_out_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "ctranslate2", None)
        whisper = HermesWhisperConfig(device=ComputeDevice.CUDA, compute_type=ComputeType.FLOAT16)
        with capture_logs() as logs:
            verify_compute_type(whisper)
        assert logs[0]["event"] == "compute_type_check_skipped"
        assert "ctranslate2 not installed" in logs[0]["reason"]

    def test_unusable_cuda_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _no_device(device: str) -> set[str]:
            raise RuntimeError("CUDA failed with error no CUDA-capable device is detected")

        monkeypatch.setitem(
            sys.modules, "ctranslate2", SimpleNamespace(get_supported_compute_types=_no_device)
        )
        whisper = HermesWhisperConfig(device=ComputeDevice.CUDA, compute_type=ComputeType.INT8)
        with pytest.raises(TranscriptionError, match="no CUDA-capable device"):
            verify_compute_type(whisper)


class TestSetupWizard:
    @pytest.fixture
    def config_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        """An 8 GB GPU, every prompt answered with Enter, config written to tmp_path."""
        monkeypatch.setenv("SOPHIA_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(
            "sophia.services.hermes_setup.detect_gpu", lambda: (True, "GTX 1070", 8192)
        )
        monkeypatch.setattr("builtins.input", lambda _prompt: "")
        return tmp_path

    @pytest.mark.parametrize(
        ("cuda_types", "expected"),
        [(PASCAL_CUDA_TYPES, "int8"), (AMPERE_CUDA_TYPES, "float16")],
        ids=["pascal", "float16-gpu"],
    )
    def test_writes_a_type_the_gpu_supports(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config_dir: Path,
        cuda_types: set[str],
        expected: str,
    ) -> None:
        from sophia.cli.lectures import lectures_setup

        _fake_ctranslate2(monkeypatch, cuda_types)
        lectures_setup()
        assert f'compute_type = "{expected}"' in (config_dir / "hermes.toml").read_text()

    def test_verification_rejects_an_unsupported_type(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config_dir: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from sophia.cli.lectures import lectures_setup

        _fake_ctranslate2(monkeypatch, PASCAL_CUDA_TYPES)
        monkeypatch.setattr(
            "sophia.services.hermes_setup.recommend_compute_type",
            lambda _device: ComputeType.FLOAT16,
        )
        with pytest.raises(SystemExit):
            lectures_setup()
        out = capsys.readouterr().out
        assert "Config verification failed" in out
        assert "Config verified" not in out


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


class TestGetProviderDefaults:
    @pytest.mark.parametrize(
        "provider",
        list(LLMProvider),
        ids=[p.value for p in LLMProvider],
    )
    def test_returns_dict_with_expected_keys(self, provider: LLMProvider) -> None:
        defaults = get_provider_defaults(provider)
        assert "model" in defaults
        assert "api_key_env" in defaults

    def test_github_defaults(self) -> None:
        defaults = get_provider_defaults(LLMProvider.GITHUB)
        assert defaults["model"] == "openai/gpt-4o"
        assert defaults["api_key_env"] == "GITHUB_TOKEN"


class TestRecommendConfigWithProvider:
    """recommend_config() with optional provider/model/api_key_env overrides."""

    def test_default_no_provider_returns_github(self) -> None:
        """Backward compat: no provider arg still returns GitHub defaults."""
        config = recommend_config(has_gpu=False, vram_mb=0)
        assert config.llm.provider == LLMProvider.GITHUB
        assert config.llm.model == "openai/gpt-4o"
        assert config.llm.api_key_env == "GITHUB_TOKEN"

    @pytest.mark.parametrize(
        "provider",
        list(LLMProvider),
        ids=[p.value for p in LLMProvider],
    )
    def test_each_provider_uses_correct_defaults(self, provider: LLMProvider) -> None:
        """When a provider is specified, its defaults are used."""
        defaults = get_provider_defaults(provider)
        config = recommend_config(has_gpu=False, vram_mb=0, provider=provider)
        assert config.llm.provider == provider
        assert config.llm.model == defaults["model"]
        assert config.llm.api_key_env == defaults["api_key_env"]

    def test_custom_model_overrides_default(self) -> None:
        config = recommend_config(
            has_gpu=False, vram_mb=0, provider=LLMProvider.GEMINI, llm_model="gemini-pro"
        )
        assert config.llm.provider == LLMProvider.GEMINI
        assert config.llm.model == "gemini-pro"
        assert config.llm.api_key_env == "SOPHIA_GEMINI_API_KEY"

    def test_custom_api_key_env_overrides_default(self) -> None:
        config = recommend_config(
            has_gpu=False, vram_mb=0, provider=LLMProvider.GITHUB, api_key_env="MY_TOKEN"
        )
        assert config.llm.api_key_env == "MY_TOKEN"
        assert config.llm.model == "openai/gpt-4o"

    def test_custom_model_and_key(self) -> None:
        config = recommend_config(
            has_gpu=True,
            vram_mb=24000,
            provider=LLMProvider.GROQ,
            llm_model="mixtral-8x7b",
            api_key_env="MY_GROQ",
        )
        assert config.llm.provider == LLMProvider.GROQ
        assert config.llm.model == "mixtral-8x7b"
        assert config.llm.api_key_env == "MY_GROQ"

    def test_whisper_still_follows_gpu_not_provider(self) -> None:
        """Provider choice must not affect Whisper model selection."""
        config_gpu = recommend_config(has_gpu=True, vram_mb=24000, provider=LLMProvider.OLLAMA)
        config_cpu = recommend_config(has_gpu=False, vram_mb=0, provider=LLMProvider.OLLAMA)
        assert config_gpu.whisper.model == WhisperModel.LARGE_V3
        assert config_cpu.whisper.model == WhisperModel.SMALL


class TestDetectGpuContext:
    """detect_gpu_context() returns 3-state context-aware GPU messages."""

    def test_cpu_image_no_gpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CPU image, no GPU detected → info message."""
        monkeypatch.delenv("SOPHIA_DOCKER", raising=False)
        with patch("os.path.exists", return_value=False):
            ctx = detect_gpu_context(has_gpu=False, gpu_name="", vram_mb=0)
        assert ctx.severity == "info"
        assert "CPU" in ctx.message

    def test_gpu_image_no_device(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GPU image (CUDA present) but no GPU device → warning."""
        monkeypatch.setenv("SOPHIA_DOCKER", "1")
        with patch("os.path.exists", return_value=True):
            ctx = detect_gpu_context(has_gpu=False, gpu_name="", vram_mb=0)
        assert ctx.severity == "warning"
        assert "nvidia-container-toolkit" in ctx.message

    def test_gpu_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GPU detected → success with device name."""
        monkeypatch.delenv("SOPHIA_DOCKER", raising=False)
        with patch("os.path.exists", return_value=False):
            ctx = detect_gpu_context(has_gpu=True, gpu_name="NVIDIA RTX 4090", vram_mb=24000)
        assert ctx.severity == "success"
        assert "NVIDIA RTX 4090" in ctx.message

    def test_gpu_context_returns_named_tuple_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SOPHIA_DOCKER", raising=False)
        with patch("os.path.exists", return_value=False):
            ctx = detect_gpu_context(has_gpu=False, gpu_name="", vram_mb=0)
        assert hasattr(ctx, "message")
        assert hasattr(ctx, "severity")
        assert hasattr(ctx, "icon")


class TestValidateApiKeyLive:
    """validate_api_key_live() makes lightweight async HTTP calls to validate keys."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_github_success(self) -> None:
        respx.get("https://models.inference.ai.azure.com/models").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        valid, msg = await validate_api_key_live(LLMProvider.GITHUB, "ghp_test123")
        assert valid is True
        assert "verified" in msg.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_github_unauthorized(self) -> None:
        respx.get("https://models.inference.ai.azure.com/models").mock(
            return_value=httpx.Response(401)
        )
        valid, msg = await validate_api_key_live(LLMProvider.GITHUB, "bad_key")
        assert valid is False
        assert "invalid" in msg.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limited(self) -> None:
        respx.get("https://api.groq.com/openai/v1/models").mock(return_value=httpx.Response(429))
        valid, msg = await validate_api_key_live(LLMProvider.GROQ, "key123")
        assert valid is True
        assert "rate" in msg.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_timeout(self) -> None:
        respx.get("https://models.inference.ai.azure.com/models").mock(
            side_effect=httpx.ConnectTimeout("timed out")
        )
        valid, msg = await validate_api_key_live(LLMProvider.GITHUB, "ghp_test123")
        assert valid is False
        assert "timed out" in msg.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_ollama_success(self) -> None:
        respx.get("http://localhost:11434/api/tags").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        valid, msg = await validate_api_key_live(LLMProvider.OLLAMA, "")
        assert valid is True
        assert "ollama" in msg.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_ollama_connection_refused(self) -> None:
        respx.get("http://localhost:11434/api/tags").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        valid, msg = await validate_api_key_live(LLMProvider.OLLAMA, "")
        assert valid is False
        assert "ollama" in msg.lower()

    @pytest.mark.asyncio
    @respx.mock
    async def test_gemini_success(self) -> None:
        respx.get("https://generativelanguage.googleapis.com/v1/models").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        valid, msg = await validate_api_key_live(LLMProvider.GEMINI, "AIza_test")
        assert valid is True
        assert "verified" in msg.lower()
