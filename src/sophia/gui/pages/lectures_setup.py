"""Hermes setup wizard — guided 4-step configuration for the lecture pipeline."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import structlog
from nicegui import app, ui

from sophia.domain.models import (
    ComputeDevice,
    ComputeType,
    HermesConfig,
    HermesWhisperConfig,
    WhisperModel,
)
from sophia.gui.middleware.health import get_container
from sophia.gui.state.storage_map import USER_HERMES_SETUP_COMPLETE
from sophia.services.hermes_setup import (
    check_hermes_deps,
    detect_gpu,
    recommend_config,
    save_hermes_config,
    validate_llm_provider,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# Storage estimates (MB): model weight + ~500 MB for transcripts/embeddings per 100h
_MODEL_STORAGE_MB: dict[WhisperModel, int] = {
    WhisperModel.LARGE_V3: 3500,
    WhisperModel.TURBO: 2000,
    WhisperModel.MEDIUM: 2000,
    WhisperModel.SMALL: 1000,
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def is_docker() -> bool:
    """Detect if running inside a Docker container."""
    return os.path.exists("/.dockerenv") or os.environ.get("SOPHIA_DOCKER") == "1"


def estimate_storage_mb(model: WhisperModel) -> int:
    """Estimated disk usage in MB for a given Whisper model size."""
    return _MODEL_STORAGE_MB.get(model, 2000)


def format_gpu_info(has_gpu: bool, gpu_name: str, vram_mb: int) -> str:
    """Format GPU detection results for display."""
    if not has_gpu:
        return "No GPU detected — CPU mode"
    vram_str = f"{vram_mb} MB VRAM" if vram_mb else ""
    return f"{gpu_name} — {vram_str}".rstrip(" —")


def format_dep_status(missing: list[str]) -> tuple[str, str, str]:
    """Return (text, icon, css_class) for dependency check result."""
    if not missing:
        return "All dependencies installed", "check_circle", "text-green-600"
    count = len(missing)
    noun = "package" if count == 1 else "packages"
    return f"{count} missing {noun}", "error", "text-red-600"


def build_config_summary(config: HermesConfig) -> list[str]:
    """Build human-readable config summary lines."""
    return [
        f"Whisper model: {config.whisper.model.value}",
        f"Device: {config.whisper.device.value}",
        f"Compute type: {config.whisper.compute_type.value}",
        f"LLM provider: {config.llm.provider.value} ({config.llm.model})",
        f"Embedding model: {config.embeddings.model}",
    ]


# ---------------------------------------------------------------------------
# Main wizard content
# ---------------------------------------------------------------------------


async def lectures_setup_content() -> None:
    """Render the 4-step Hermes setup wizard."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")  # pyright: ignore[reportUnknownMemberType]
        return

    ui.label("Lecture Pipeline Setup").classes("text-2xl font-bold mb-4")  # pyright: ignore[reportUnknownMemberType]

    config_state: dict[str, Any] = {}

    with ui.stepper().props(":header-nav=false").classes("w-full") as stepper:  # pyright: ignore[reportUnknownMemberType]
        with ui.step("Dependencies"):  # pyright: ignore[reportUnknownMemberType]
            _render_deps_step(stepper)

        with ui.step("GPU & Compute"):  # pyright: ignore[reportUnknownMemberType]
            _render_gpu_step(stepper, config_state)

        with ui.step("Storage"):  # pyright: ignore[reportUnknownMemberType]
            _render_storage_step(stepper, config_state, container)

        with ui.step("Save & Complete"):  # pyright: ignore[reportUnknownMemberType]
            _render_save_step(stepper, config_state, container)


# ---------------------------------------------------------------------------
# Step renderers
# ---------------------------------------------------------------------------


def _render_deps_step(stepper: ui.stepper) -> None:  # pyright: ignore[reportUnknownParameterType]
    """Step 1 — check and optionally install Hermes dependencies."""
    missing = check_hermes_deps()
    text, icon, css = format_dep_status(missing)

    with ui.row().classes("items-center gap-2"):  # pyright: ignore[reportUnknownMemberType]
        ui.icon(icon).classes(f"text-2xl {css}")  # pyright: ignore[reportUnknownMemberType]
        ui.label(text).classes(f"text-lg font-medium {css}")  # pyright: ignore[reportUnknownMemberType]

    if missing:
        ui.label("Missing packages:").classes("mt-2 font-medium")  # pyright: ignore[reportUnknownMemberType]
        for pkg in missing:
            with ui.row().classes("items-center gap-1 ml-4"):  # pyright: ignore[reportUnknownMemberType]
                ui.icon("close").classes("text-red-500 text-sm")  # pyright: ignore[reportUnknownMemberType]
                ui.label(pkg).classes("font-mono text-sm")  # pyright: ignore[reportUnknownMemberType]

        ui.separator()  # pyright: ignore[reportUnknownMemberType]
        ui.label("Install with:").classes("mt-2 text-sm text-gray-600")  # pyright: ignore[reportUnknownMemberType]
        ui.code("pip install sophia[hermes]").classes("mt-1")  # pyright: ignore[reportUnknownMemberType]

        async def _check_again() -> None:
            ui.notify("Checking dependencies...", type="info")  # pyright: ignore[reportUnknownMemberType]
            ui.navigate.to("/lectures/setup")  # pyright: ignore[reportUnknownMemberType]

        with ui.row().classes("mt-4 gap-2"):  # pyright: ignore[reportUnknownMemberType]
            ui.button("Check Again", icon="refresh", on_click=_check_again)  # pyright: ignore[reportUnknownMemberType]
    else:
        stepper.next()  # pyright: ignore[reportUnknownMemberType]


def _render_gpu_step(stepper: ui.stepper, config_state: dict[str, Any]) -> None:  # pyright: ignore[reportUnknownParameterType]
    """Step 2 — detect GPU hardware and recommend compute settings."""
    has_gpu, gpu_name, vram_mb = detect_gpu()
    gpu_text = format_gpu_info(has_gpu, gpu_name, vram_mb)
    recommended = recommend_config(has_gpu, vram_mb)

    if is_docker():
        with (
            ui.card().classes("w-full bg-blue-50 border-l-4 border-blue-400 mb-4"),  # pyright: ignore[reportUnknownMemberType]
            ui.row().classes("items-center gap-2"),  # pyright: ignore[reportUnknownMemberType]
        ):
            ui.icon("info").classes("text-blue-600")  # pyright: ignore[reportUnknownMemberType]
            ui.label(  # pyright: ignore[reportUnknownMemberType]
                "Running in Docker — GPU requires nvidia-container-toolkit."
            ).classes("text-sm text-blue-800")
            ui.link(  # pyright: ignore[reportUnknownMemberType]
                "Setup guide",
                "https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html",
                new_tab=True,
            ).classes("text-xs text-blue-600 underline")

    gpu_icon = "memory" if has_gpu else "computer"
    with ui.row().classes("items-center gap-2 mb-4"):  # pyright: ignore[reportUnknownMemberType]
        ui.icon(gpu_icon).classes("text-2xl")  # pyright: ignore[reportUnknownMemberType]
        ui.label(gpu_text).classes("text-lg font-medium")  # pyright: ignore[reportUnknownMemberType]

    if has_gpu and vram_mb:
        ui.label(  # pyright: ignore[reportUnknownMemberType]
            f"Recommended Whisper model: {recommended.whisper.model.value}"
        ).classes("text-sm text-gray-600 mb-2")
    else:
        ui.label(  # pyright: ignore[reportUnknownMemberType]
            "Recommended: small model for CPU transcription (~2× real-time)"
        ).classes("text-sm text-gray-600 mb-2")

    model_options = [m.value for m in WhisperModel]
    selected_model = ui.select(  # pyright: ignore[reportUnknownMemberType]
        options=model_options,
        value=recommended.whisper.model.value,
        label="Whisper Model",
    ).classes("w-60")

    config_state["recommended"] = recommended
    config_state["has_gpu"] = has_gpu

    def _on_model_change() -> None:
        config_state["model_override"] = selected_model.value  # pyright: ignore[reportUnknownMemberType]

    selected_model.on_value_change(_on_model_change)  # pyright: ignore[reportUnknownMemberType]

    with ui.row().classes("mt-4 gap-2"):  # pyright: ignore[reportUnknownMemberType]
        ui.button("Back", on_click=stepper.previous)  # pyright: ignore[reportUnknownMemberType]
        ui.button("Next", on_click=stepper.next)  # pyright: ignore[reportUnknownMemberType]


def _render_storage_step(  # pyright: ignore[reportUnknownParameterType]
    stepper: ui.stepper, config_state: dict[str, Any], container: AppContainer
) -> None:
    """Step 3 — show storage requirements and data directory."""
    recommended = config_state.get("recommended")
    model = recommended.whisper.model if recommended else WhisperModel.SMALL
    storage_mb = estimate_storage_mb(model)

    with ui.card().classes("w-full mb-4"):  # pyright: ignore[reportUnknownMemberType]
        ui.label("Storage Requirements").classes("text-lg font-semibold mb-2")  # pyright: ignore[reportUnknownMemberType]
        ui.separator()  # pyright: ignore[reportUnknownMemberType]

        with ui.row().classes("items-center gap-2 mt-2"):  # pyright: ignore[reportUnknownMemberType]
            ui.icon("storage").classes("text-xl text-gray-500")  # pyright: ignore[reportUnknownMemberType]
            ui.label(f"Estimated disk usage: ~{storage_mb / 1000:.1f} GB").classes("text-sm")  # pyright: ignore[reportUnknownMemberType]

        ui.label(f"Model weights: ~{storage_mb - 500} MB").classes("text-sm text-gray-500 ml-8")  # pyright: ignore[reportUnknownMemberType]
        ui.label(  # pyright: ignore[reportUnknownMemberType]
            "Transcripts + embeddings: ~500 MB per 100h of lectures"
        ).classes("text-sm text-gray-500 ml-8")

    with ui.card().classes("w-full mb-4"):  # pyright: ignore[reportUnknownMemberType]
        ui.label("Data Directory").classes("text-lg font-semibold mb-2")  # pyright: ignore[reportUnknownMemberType]
        ui.separator()  # pyright: ignore[reportUnknownMemberType]
        data_dir = str(container.settings.data_dir)
        config_dir = str(container.settings.config_dir)
        with ui.row().classes("items-center gap-4 mt-2"):  # pyright: ignore[reportUnknownMemberType]
            ui.label("Data:").classes("text-sm text-gray-500 w-20")  # pyright: ignore[reportUnknownMemberType]
            ui.label(data_dir).classes("text-sm font-mono")  # pyright: ignore[reportUnknownMemberType]
        with ui.row().classes("items-center gap-4 mt-1"):  # pyright: ignore[reportUnknownMemberType]
            ui.label("Config:").classes("text-sm text-gray-500 w-20")  # pyright: ignore[reportUnknownMemberType]
            ui.label(config_dir).classes("text-sm font-mono")  # pyright: ignore[reportUnknownMemberType]

    if is_docker():
        with (
            ui.card().classes("w-full bg-amber-50 border-l-4 border-amber-400"),  # pyright: ignore[reportUnknownMemberType]
            ui.row().classes("items-center gap-2"),  # pyright: ignore[reportUnknownMemberType]
        ):
            ui.icon("warning").classes("text-amber-600")  # pyright: ignore[reportUnknownMemberType]
            ui.label(  # pyright: ignore[reportUnknownMemberType]
                "Ensure a volume is mounted for data persistence in Docker."
            ).classes("text-sm text-amber-800")

    with ui.row().classes("mt-4 gap-2"):  # pyright: ignore[reportUnknownMemberType]
        ui.button("Back", on_click=stepper.previous)  # pyright: ignore[reportUnknownMemberType]
        ui.button("Next", on_click=stepper.next)  # pyright: ignore[reportUnknownMemberType]


def _render_save_step(  # pyright: ignore[reportUnknownParameterType]
    stepper: ui.stepper, config_state: dict[str, Any], container: AppContainer
) -> None:
    """Step 4 — review config summary and save."""
    recommended = config_state.get("recommended")
    if recommended is None:
        ui.label("Error: no configuration generated. Go back to Step 2.").classes("text-red-600")  # pyright: ignore[reportUnknownMemberType]
        ui.button("Back", on_click=stepper.previous)  # pyright: ignore[reportUnknownMemberType]
        return

    def _resolve_final_config() -> HermesConfig:
        """Resolve the final config from current state at call-time."""
        override = config_state.get("model_override")
        if override:
            return _apply_model_override(
                recommended, WhisperModel(override), config_state.get("has_gpu", False)
            )
        return recommended

    def _on_save() -> None:
        final = _resolve_final_config()
        _complete_setup(final, container.settings.config_dir)

    summary_lines = build_config_summary(recommended)
    with ui.card().classes("w-full mb-4"):  # pyright: ignore[reportUnknownMemberType]
        ui.label("Configuration Summary").classes("text-lg font-semibold mb-2")  # pyright: ignore[reportUnknownMemberType]
        ui.separator()  # pyright: ignore[reportUnknownMemberType]
        for line in summary_lines:
            ui.label(line).classes("text-sm font-mono mt-1")  # pyright: ignore[reportUnknownMemberType]
        ui.label(  # pyright: ignore[reportUnknownMemberType]
            "Note: if you changed the Whisper model, the saved config will reflect your selection."
        ).classes("text-xs text-gray-400 mt-2 italic")

    valid, msg = validate_llm_provider(recommended.llm)
    icon_name = "check_circle" if valid else "warning"
    css = "text-green-600" if valid else "text-amber-600"
    with ui.row().classes("items-center gap-2 mt-2"):  # pyright: ignore[reportUnknownMemberType]
        ui.icon(icon_name).classes(f"text-lg {css}")  # pyright: ignore[reportUnknownMemberType]
        ui.label(msg).classes(f"text-sm {css}")  # pyright: ignore[reportUnknownMemberType]

    with ui.row().classes("mt-4 gap-2"):  # pyright: ignore[reportUnknownMemberType]
        ui.button("Back", on_click=stepper.previous)  # pyright: ignore[reportUnknownMemberType]
        ui.button(  # pyright: ignore[reportUnknownMemberType]
            "Save & Complete",
            icon="check",
            on_click=_on_save,
            color="primary",
        )


# ---------------------------------------------------------------------------
# Actions & helpers
# ---------------------------------------------------------------------------


def _apply_model_override(config: HermesConfig, model: WhisperModel, has_gpu: bool) -> HermesConfig:
    """Create a new config with the user's model selection."""
    device = config.whisper.device
    compute_type = config.whisper.compute_type
    if not has_gpu:
        device = ComputeDevice.CPU
        compute_type = ComputeType.FLOAT32
    return HermesConfig(
        whisper=HermesWhisperConfig(
            model=model,
            device=device,
            compute_type=compute_type,
            vad_filter=config.whisper.vad_filter,
            language=config.whisper.language,
        ),
        llm=config.llm,
        embeddings=config.embeddings,
    )


def _complete_setup(config: HermesConfig, config_dir: Path) -> None:
    """Save config, mark setup as complete, and redirect."""
    save_hermes_config(config, config_dir)
    app.storage.user[USER_HERMES_SETUP_COMPLETE] = True  # pyright: ignore[reportUnknownMemberType]
    ui.notify("Lecture pipeline configured successfully!", type="positive")  # pyright: ignore[reportUnknownMemberType]
    ui.navigate.to("/lectures")  # pyright: ignore[reportUnknownMemberType]
    log.info("hermes_setup_complete", config=config.model_dump())
