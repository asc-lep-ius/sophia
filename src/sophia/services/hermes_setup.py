"""Hermes setup service — hardware detection, config recommendation, and persistence."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from typing import TYPE_CHECKING

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


def recommend_config(has_gpu: bool, vram_mb: int) -> HermesConfig:
    """Generate recommended config based on detected hardware."""
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

    defaults = _PROVIDER_DEFAULTS[LLMProvider.GITHUB]
    llm = HermesLLMConfig(
        provider=LLMProvider.GITHUB,
        model=defaults["model"],
        api_key_env=defaults["api_key_env"],
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


_HERMES_PACKAGES: list[tuple[str, str]] = [
    ("faster_whisper", "faster-whisper"),
    ("chromadb", "chromadb"),
    ("sentence_transformers", "sentence-transformers"),
    ("openai", "openai"),
]


def check_hermes_deps() -> list[str]:
    """Return names of missing hermes dependencies."""
    missing: list[str] = []
    for mod, name in _HERMES_PACKAGES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(name)
    return missing


def install_hermes_extras() -> tuple[bool, str]:
    """Install sophia[hermes] via uv. Returns (success, output)."""
    try:
        result = subprocess.run(
            ["uv", "pip", "install", "-e", ".[hermes]"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
