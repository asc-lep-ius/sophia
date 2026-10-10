"""What the worker checks before it offers to process anything.

A missing GPU or Hermes install is reported as a reason, never swallowed: the
worker heartbeats it, the API refuses Process with it, and the log says it
once at startup (#128). Everything here runs without touching the GPU, so the
worker's own process never initialises CUDA — the stages do that in their own
processes.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from sophia.domain.models import ComputeDevice
from sophia.services.hermes_setup import detect_gpu, load_hermes_config

if TYPE_CHECKING:
    from sophia.config import Settings

log = structlog.get_logger()

# The packages the hermes extra installs, by the name they are imported as.
HERMES_MODULES = ("faster_whisper", "ctranslate2", "sentence_transformers", "chromadb")


@dataclass(frozen=True, slots=True)
class WorkerCapability:
    capable: bool
    reason: str = ""
    gpu_name: str = ""


def probe_capability(settings: Settings) -> WorkerCapability:
    """Say whether this process could run the pipeline, and if not, why."""
    missing = [name for name in HERMES_MODULES if importlib.util.find_spec(name) is None]
    if missing:
        return WorkerCapability(
            False,
            f"Hermes is not installed here (missing {', '.join(missing)}) — "
            "build the worker image with the hermes extra",
        )

    config = load_hermes_config(settings.config_dir)
    if config is None:
        return WorkerCapability(
            False, f"Hermes is not configured — no hermes.toml in {settings.config_dir}"
        )
    if config.whisper.device != ComputeDevice.CUDA:
        return WorkerCapability(
            False,
            f"hermes.toml sets whisper.device = {config.whisper.device.value}; "
            "processing from the browser needs the GPU (CPU transcription is out of scope)",
        )

    # nvidia-smi, not CUDA: this process must never hold a context on the GPU
    # the stages need. Whether Whisper's compute type runs on it is checked by
    # the media stage itself, in its own process, before anything is loaded.
    has_gpu, gpu_name, vram_mb = detect_gpu()
    if not has_gpu:
        return WorkerCapability(
            False, "No usable NVIDIA GPU: nvidia-smi found none — is the container given one?"
        )

    log.info("worker_capable", gpu=gpu_name, vram_mb=vram_mb, whisper=config.whisper.model.value)
    return WorkerCapability(True, gpu_name=gpu_name)
