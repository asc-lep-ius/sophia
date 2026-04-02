"""Hermes setup service — hardware detection, config recommendation, and persistence."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

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

if TYPE_CHECKING:
    from pathlib import Path

_HERMES_TOML = "hermes.toml"


# VRAM thresholds (MiB) for Whisper model selection
_HIGH_VRAM_THRESHOLD = 8000
_LOW_VRAM_THRESHOLD = 4000

_PROVIDER_DEFAULTS: dict[LLMProvider, dict[str, str]] = {
    LLMProvider.GITHUB: {
        "model": "openai/gpt-4o",
        "api_key_env": "GITHUB_TOKEN",
        "embedding_model": "openai/text-embedding-3-small",
    },
    LLMProvider.GEMINI: {
        "model": "gemini-2.0-flash",
        "api_key_env": "SOPHIA_GEMINI_API_KEY",
        "embedding_model": "text-embedding-004",
    },
    LLMProvider.GROQ: {
        "model": "llama-3.3-70b-versatile",
        "api_key_env": "SOPHIA_GROQ_API_KEY",
        "embedding_model": "",
    },
    LLMProvider.OLLAMA: {
        "model": "llama3.2",
        "api_key_env": "",
        "embedding_model": "nomic-embed-text",
    },
}

_PROVIDER_VALIDATION_URLS: dict[LLMProvider, str] = {
    LLMProvider.GITHUB: "https://models.inference.ai.azure.com/models",
    LLMProvider.GEMINI: "https://generativelanguage.googleapis.com/v1/models",
    LLMProvider.GROQ: "https://api.groq.com/openai/v1/models",
    LLMProvider.OLLAMA: "http://localhost:11434/api/tags",
}

_VALIDATION_TIMEOUT_SECONDS = 5


@dataclass(frozen=True, slots=True)
class GpuContext:
    """GPU detection context for UI messaging."""

    message: str
    severity: str
    icon: str


def detect_gpu() -> tuple[bool, str, int]:
    """Detect GPU availability via nvidia-smi.

    Returns (has_gpu, gpu_name, vram_mb).
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "-q", "-d", "MEMORY"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, "", 0

    if result.returncode != 0:
        return False, "", 0

    # Parse VRAM from nvidia-smi memory query
    vram_mb = 0
    for match in re.finditer(r"Total\s*:\s*(\d+)\s*MiB", result.stdout):
        vram_mb = int(match.group(1))
        break  # first GPU

    # Get GPU name from a separate query
    gpu_name = ""
    try:
        name_result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if name_result.returncode == 0:
            gpu_name = name_result.stdout.strip().split("\n")[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return True, gpu_name, vram_mb


def recommend_config(
    has_gpu: bool,
    vram_mb: int,
    *,
    provider: LLMProvider | None = None,
    llm_model: str | None = None,
    api_key_env: str | None = None,
) -> HermesConfig:
    """Generate recommended config based on detected hardware.

    When *provider* is given, its defaults are used for the LLM section.
    *llm_model* and *api_key_env* override the provider defaults when supplied.
    """
    if has_gpu and vram_mb >= _HIGH_VRAM_THRESHOLD:
        whisper = HermesWhisperConfig(
            model=WhisperModel.LARGE_V3,
            device=ComputeDevice.CUDA,
            compute_type=ComputeType.FLOAT16,
        )
    elif has_gpu and vram_mb >= _LOW_VRAM_THRESHOLD:
        whisper = HermesWhisperConfig(
            model=WhisperModel.TURBO,
            device=ComputeDevice.CUDA,
            compute_type=ComputeType.FLOAT16,
        )
    else:
        whisper = HermesWhisperConfig(
            model=WhisperModel.SMALL,
            device=ComputeDevice.CPU,
            compute_type=ComputeType.FLOAT32,
        )

    selected = provider or LLMProvider.GITHUB
    defaults = _PROVIDER_DEFAULTS[selected]
    llm = HermesLLMConfig(
        provider=selected,
        model=llm_model or defaults["model"],
        api_key_env=api_key_env if api_key_env is not None else defaults["api_key_env"],
    )
    embeddings = HermesEmbeddingConfig(
        provider=EmbeddingProvider.LOCAL,
        model="intfloat/multilingual-e5-large",
    )

    return HermesConfig(whisper=whisper, llm=llm, embeddings=embeddings)


def save_hermes_config(config: HermesConfig, config_dir: Path) -> Path:
    """Save config as TOML to config_dir/hermes.toml."""
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / _HERMES_TOML

    lines = [
        "[whisper]",
        f'model = "{config.whisper.model.value}"',
        f'device = "{config.whisper.device.value}"',
        f'compute_type = "{config.whisper.compute_type.value}"',
        f"vad_filter = {str(config.whisper.vad_filter).lower()}",
        f'language = "{config.whisper.language}"',
        "",
        "[llm]",
        f'provider = "{config.llm.provider.value}"',
        f'model = "{config.llm.model}"',
        f'api_key_env = "{config.llm.api_key_env}"',
        "",
        "[embeddings]",
        f'provider = "{config.embeddings.provider.value}"',
        f'model = "{config.embeddings.model}"',
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def load_hermes_config(config_dir: Path) -> HermesConfig | None:
    """Load config from config_dir/hermes.toml, or None if not set up."""
    path = config_dir / _HERMES_TOML
    if not path.exists():
        return None

    data = tomllib.loads(path.read_text())

    whisper_data = data.get("whisper", {})
    llm_data = data.get("llm", {})
    embed_data = data.get("embeddings", {})

    return HermesConfig(
        whisper=HermesWhisperConfig(**whisper_data),
        llm=HermesLLMConfig(**llm_data),
        embeddings=HermesEmbeddingConfig(**embed_data),
    )


def validate_llm_provider(config: HermesLLMConfig) -> tuple[bool, str]:
    """Check if required API key env var is set. Returns (valid, message)."""
    if not config.api_key_env:
        return True, f"{config.provider.value}: no API key required"

    value = os.environ.get(config.api_key_env, "")
    if value:
        return True, f"{config.api_key_env} is set"
    return False, f"{config.api_key_env} is not set — export it before running Hermes"


def get_provider_defaults(provider: LLMProvider) -> dict[str, str]:
    """Return default model/api_key_env/embedding_model for a provider."""
    return dict(_PROVIDER_DEFAULTS[provider])


def detect_gpu_context(has_gpu: bool, gpu_name: str, vram_mb: int) -> GpuContext:
    """Return a 3-state context message based on GPU availability and Docker image type."""
    if has_gpu:
        return GpuContext(
            message=f"GPU detected: {gpu_name}. Whisper will use GPU acceleration.",
            severity="success",
            icon="check_circle",
        )

    is_cuda_image = os.path.exists("/usr/local/cuda/") and os.environ.get("SOPHIA_DOCKER") == "1"
    if is_cuda_image:
        return GpuContext(
            message=(
                "GPU image detected but no GPU device is available. "
                "Ensure nvidia-container-toolkit is installed on the host "
                "and you started with `docker compose --profile gpu up`."
            ),
            severity="warning",
            icon="warning",
        )

    return GpuContext(
        message=(
            "You're running the CPU image. Whisper will use CPU mode "
            "— this is expected and works fine (transcription will be slower)."
        ),
        severity="info",
        icon="info",
    )


async def validate_api_key_live(provider: LLMProvider, api_key: str) -> tuple[bool, str]:
    """Validate an API key by making a lightweight HTTP request to the provider."""
    url = _PROVIDER_VALIDATION_URLS[provider]
    is_ollama = provider == LLMProvider.OLLAMA

    headers: dict[str, str] = {}
    params: dict[str, str] = {}

    if provider == LLMProvider.GEMINI:
        params["key"] = api_key
    elif not is_ollama:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=_VALIDATION_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=headers, params=params)
    except (httpx.ConnectTimeout, httpx.ReadTimeout):
        return False, "Connection timed out"
    except httpx.ConnectError:
        if is_ollama:
            return False, "Cannot connect to Ollama — is it running on localhost:11434?"
        return False, f"Cannot connect to {provider.value} API"

    if resp.status_code == 200:  # noqa: PLR2004
        if is_ollama:
            return True, "Connected to Ollama"
        return True, "Key verified"
    if resp.status_code == 401:  # noqa: PLR2004
        return False, "Invalid API key"
    if resp.status_code == 429:  # noqa: PLR2004
        return True, "Key format looks valid but rate-limited — try again later"

    return False, f"Unexpected response ({resp.status_code})"
