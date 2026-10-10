"""What the worker refuses to do, and why it says so (#128)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sophia.domain.models import ComputeDevice, HermesConfig, HermesWhisperConfig
from sophia.services.hermes_setup import save_hermes_config
from sophia.worker import capability

if TYPE_CHECKING:
    from sophia.config import Settings


@pytest.fixture
def cuda_config(settings: Settings) -> None:
    whisper = HermesWhisperConfig(device=ComputeDevice.CUDA)
    save_hermes_config(HermesConfig(whisper=whisper), settings.config_dir)


def test_missing_hermes_extra_is_named(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, cuda_config: None
) -> None:
    monkeypatch.setattr(
        capability.importlib.util,
        "find_spec",
        lambda name: None if name == "faster_whisper" else object(),
    )

    probed = capability.probe_capability(settings)

    assert probed.capable is False
    assert "missing faster_whisper" in probed.reason


def test_no_gpu_is_a_visible_refusal(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, cuda_config: None
) -> None:
    monkeypatch.setattr(capability.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(capability, "detect_gpu", lambda: (False, "", 0))

    probed = capability.probe_capability(settings)

    assert probed.capable is False
    assert probed.reason.startswith("No usable NVIDIA GPU")


def test_a_cpu_config_is_refused_rather_than_run_slowly(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_hermes_config(HermesConfig(), settings.config_dir)
    monkeypatch.setattr(capability.importlib.util, "find_spec", lambda _name: object())

    probed = capability.probe_capability(settings)

    assert probed.capable is False
    assert "whisper.device = cpu" in probed.reason


def test_a_gpu_box_with_hermes_is_capable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, cuda_config: None
) -> None:
    monkeypatch.setattr(capability.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(capability, "detect_gpu", lambda: (True, "NVIDIA GeForce GTX 1070", 8192))

    probed = capability.probe_capability(settings)

    assert probed == capability.WorkerCapability(True, gpu_name="NVIDIA GeForce GTX 1070")
