"""Hermes setup wizard — guided 2-step configuration for the lecture pipeline."""

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
    LLMProvider,
    WhisperModel,
)
from sophia.gui.middleware.health import get_container
from sophia.gui.state.storage_map import USER_HERMES_SETUP_COMPLETE
from sophia.services.hermes_setup import (
    GpuContext,
    detect_gpu,
    detect_gpu_context,
    get_provider_defaults,
    load_hermes_config,
    recommend_config,
    save_hermes_config,
    validate_api_key_live,
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

# Approximate model download sizes (MB) for first-use warning
_MODEL_DOWNLOAD_MB: dict[WhisperModel, int] = {
    WhisperModel.LARGE_V3: 3100,
    WhisperModel.TURBO: 1500,
    WhisperModel.MEDIUM: 1500,
    WhisperModel.SMALL: 500,
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


def estimate_download_mb(model: WhisperModel) -> int:
    """Approximate download size in MB for the Whisper model weights."""
    return _MODEL_DOWNLOAD_MB.get(model, 1500)


def format_gpu_info(has_gpu: bool, gpu_name: str, vram_mb: int) -> str:
    """Format GPU detection results for display."""
    if not has_gpu:
        return "No GPU detected — CPU mode"
    vram_str = f"{vram_mb} MB VRAM" if vram_mb else ""
    return f"{gpu_name} — {vram_str}".rstrip(" —")


def build_config_summary(config: HermesConfig) -> list[str]:
    """Build human-readable config summary lines."""
    return [
        f"Whisper model: {config.whisper.model.value}",
        f"Device: {config.whisper.device.value}",
        f"Compute type: {config.whisper.compute_type.value}",
        f"LLM provider: {config.llm.provider.value} ({config.llm.model})",
        f"Embedding model: {config.embeddings.model}",
    ]


_PROVIDER_LABELS: dict[LLMProvider, str] = {
    LLMProvider.GITHUB: "GitHub Models",
    LLMProvider.GEMINI: "Google Gemini",
    LLMProvider.GROQ: "Groq",
    LLMProvider.OLLAMA: "Ollama (local)",
}


def build_provider_label(provider: LLMProvider) -> str:
    """Human-friendly label for the provider dropdown."""
    return _PROVIDER_LABELS[provider]


def needs_api_key(provider: LLMProvider) -> bool:
    """Whether the provider requires an API key (Ollama runs locally)."""
    return provider != LLMProvider.OLLAMA


# ---------------------------------------------------------------------------
# Main wizard content
# ---------------------------------------------------------------------------


async def lectures_setup_content() -> None:
    """Render the 2-step Hermes setup wizard."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")
        return

    ui.label("Lecture Pipeline Setup").classes("text-2xl font-bold mb-4")

    config_state: dict[str, Any] = {}
    existing_config = load_hermes_config(container.settings.config_dir)
    config_state["existing_config"] = existing_config

    with ui.stepper().props(":header-nav=false").classes("w-full") as stepper:
        with ui.step("GPU, Compute & LLM"):
            _render_gpu_step(stepper, config_state)

        with ui.step("Review & Save"):
            _render_review_step(stepper, config_state, container)


# ---------------------------------------------------------------------------
# Step renderers
# ---------------------------------------------------------------------------


def _render_gpu_step(stepper: ui.stepper, config_state: dict[str, Any]) -> None:
    """Step 1 — detect GPU, recommend compute settings, select LLM provider."""
    has_gpu, gpu_name, vram_mb = detect_gpu()
    recommended = recommend_config(has_gpu, vram_mb)
    existing: HermesConfig | None = config_state.get("existing_config")

    # --- Context-aware GPU messaging ---
    gpu_ctx = detect_gpu_context(has_gpu, gpu_name, vram_mb)
    _render_gpu_context_card(gpu_ctx)

    if has_gpu and vram_mb:
        ui.label(f"Recommended Whisper model: {recommended.whisper.model.value}").classes(
            "text-sm text-gray-600 mb-2"
        )
    else:
        ui.label("Recommended: small model for CPU transcription (~2× real-time)").classes(
            "text-sm text-gray-600 mb-2"
        )

    model_options = [m.value for m in WhisperModel]
    initial_model = existing.whisper.model.value if existing else recommended.whisper.model.value
    selected_model = ui.select(
        options=model_options,
        value=initial_model,
        label="Whisper Model",
    ).classes("w-60")

    config_state["recommended"] = recommended
    config_state["has_gpu"] = has_gpu
    config_state["vram_mb"] = vram_mb

    def _on_model_change() -> None:
        config_state["model_override"] = selected_model.value

    selected_model.on_value_change(_on_model_change)

    # --- LLM provider section ---
    ui.separator().classes("my-4")
    ui.label("LLM Provider").classes("text-lg font-semibold mb-2")

    provider_options = {p.value: build_provider_label(p) for p in LLMProvider}
    initial_provider = existing.llm.provider.value if existing else LLMProvider.GITHUB.value
    initial_defaults = get_provider_defaults(LLMProvider(initial_provider))

    provider_select = ui.select(
        options=provider_options,
        value=initial_provider,
        label="LLM Provider",
    ).classes("w-60")

    initial_llm_model = existing.llm.model if existing else initial_defaults["model"]
    model_input = ui.select(
        options=[initial_llm_model],
        value=initial_llm_model,
        label="LLM Model",
    ).classes("w-60")

    # API key section — hidden for Ollama
    has_existing_key = existing is not None and needs_api_key(LLMProvider(initial_provider))
    config_state["keep_existing_key"] = has_existing_key

    api_key_env = initial_defaults["api_key_env"]
    with ui.column().classes("mt-2") as api_key_col:
        if has_existing_key:
            keep_toggle = ui.toggle(
                ["Keep existing", "Enter new"],
                value="Keep existing",
            ).classes("mb-2")

            masked_label = ui.label("API key: ••••••").classes("text-sm font-mono text-gray-500")
            api_key_input = (
                ui.input(
                    label=api_key_env,
                    password=True,
                    password_toggle_button=True,
                )
                .classes("w-60")
                .props('input-class="font-mono"')
            )
            api_key_input.set_visibility(False)

            def _on_toggle_change() -> None:
                entering_new = keep_toggle.value == "Enter new"
                config_state["keep_existing_key"] = not entering_new
                masked_label.set_visibility(not entering_new)
                api_key_input.set_visibility(entering_new)

            keep_toggle.on_value_change(_on_toggle_change)
        else:
            api_key_input = (
                ui.input(
                    label=api_key_env,
                    password=True,
                    password_toggle_button=True,
                )
                .classes("w-60")
                .props('input-class="font-mono"')
            )

    api_key_col.bind_visibility_from(
        provider_select, "value", backward=lambda v: v != LLMProvider.OLLAMA.value
    )

    # Store initial LLM state
    config_state["provider"] = initial_provider
    config_state["llm_model"] = initial_llm_model
    config_state["api_key_env"] = api_key_env

    def _on_provider_change() -> None:
        prov = LLMProvider(provider_select.value)
        defaults = get_provider_defaults(prov)
        model_input.options = [defaults["model"]]
        model_input.value = defaults["model"]
        api_key_input.label = defaults["api_key_env"]
        config_state["provider"] = prov.value
        config_state["llm_model"] = defaults["model"]
        config_state["api_key_env"] = defaults["api_key_env"]
        config_state["keep_existing_key"] = False

    def _on_llm_model_change() -> None:
        config_state["llm_model"] = model_input.value

    def _on_api_key_change() -> None:
        config_state["api_key_value"] = api_key_input.value

    provider_select.on_value_change(_on_provider_change)
    model_input.on_value_change(_on_llm_model_change)
    api_key_input.on_value_change(_on_api_key_change)

    with ui.row().classes("mt-4 gap-2"):
        ui.button("Review Settings", on_click=stepper.next)


def _render_gpu_context_card(gpu_ctx: GpuContext) -> None:
    """Render a color-coded card for the GPU detection result."""
    _SEVERITY_STYLES: dict[str, tuple[str, str]] = {
        "success": ("bg-green-50 border-l-4 border-green-400", "text-green-800"),
        "warning": ("bg-amber-50 border-l-4 border-amber-400", "text-amber-800"),
        "info": ("bg-blue-50 border-l-4 border-blue-400", "text-blue-800"),
    }
    card_cls, text_cls = _SEVERITY_STYLES.get(gpu_ctx.severity, _SEVERITY_STYLES["info"])
    with (
        ui.card().classes(f"w-full {card_cls} mb-4"),
        ui.row().classes("items-center gap-2"),
    ):
        ui.icon(gpu_ctx.icon).classes(f"text-2xl {text_cls}")
        ui.label(gpu_ctx.message).classes(f"text-sm {text_cls}")


def _render_review_step(
    stepper: ui.stepper, config_state: dict[str, Any], container: AppContainer
) -> None:
    """Step 2 — review storage, download warning, config summary, and save."""
    recommended = config_state.get("recommended")
    if recommended is None:
        ui.label("Error: no configuration generated. Go back to Step 1.").classes("text-red-600")
        ui.button("Back", on_click=stepper.previous)
        return

    def _resolve_final_config() -> HermesConfig:
        """Resolve the final config from current state at call-time."""
        override_val = config_state.get("model_override")
        provider_val = config_state.get("provider")
        llm_model = config_state.get("llm_model")
        api_key_env = config_state.get("api_key_env")
        base = recommend_config(
            config_state.get("has_gpu", False),
            config_state.get("vram_mb", 0),
            provider=LLMProvider(provider_val) if provider_val else None,
            llm_model=llm_model,
            api_key_env=api_key_env,
        )
        if override_val:
            return _apply_model_override(
                base, WhisperModel(override_val), config_state.get("has_gpu", False)
            )
        return base

    # --- Storage estimate (merged from old storage step) ---
    model = recommended.whisper.model if recommended else WhisperModel.SMALL
    override = config_state.get("model_override")
    if override:
        model = WhisperModel(override)
    storage_mb = estimate_storage_mb(model)

    with ui.card().classes("w-full mb-4"):
        ui.label("Storage Requirements").classes("text-lg font-semibold mb-2")
        ui.separator()

        with ui.row().classes("items-center gap-2 mt-2"):
            ui.icon("storage").classes("text-xl text-gray-500")
            ui.label(f"Estimated disk usage: ~{storage_mb / 1000:.1f} GB").classes("text-sm")

        ui.label(f"Model weights: ~{storage_mb - 500} MB").classes("text-sm text-gray-500 ml-8")
        ui.label("Transcripts + embeddings: ~500 MB per 100h of lectures").classes(
            "text-sm text-gray-500 ml-8"
        )

    # --- Data directory ---
    with ui.card().classes("w-full mb-4"):
        ui.label("Data Directory").classes("text-lg font-semibold mb-2")
        ui.separator()
        data_dir = str(container.settings.data_dir)
        config_dir = str(container.settings.config_dir)
        with ui.row().classes("items-center gap-4 mt-2"):
            ui.label("Data:").classes("text-sm text-gray-500 w-20")
            ui.label(data_dir).classes("text-sm font-mono")
        with ui.row().classes("items-center gap-4 mt-1"):
            ui.label("Config:").classes("text-sm text-gray-500 w-20")
            ui.label(config_dir).classes("text-sm font-mono")

    # --- Docker volume warning ---
    if is_docker():
        with (
            ui.card().classes("w-full bg-amber-50 border-l-4 border-amber-400 mb-4"),
            ui.row().classes("items-center gap-2"),
        ):
            ui.icon("warning").classes("text-amber-600")
            ui.label("Ensure a volume is mounted for data persistence in Docker.").classes(
                "text-sm text-amber-800"
            )

    # --- Model download size warning ---
    download_mb = estimate_download_mb(model)
    download_gb = download_mb / 1000
    _LARGE_DOWNLOAD_THRESHOLD_MB = 1000
    if download_mb >= _LARGE_DOWNLOAD_THRESHOLD_MB:
        dl_text = (
            f"\u26a0 First use will download the Whisper model (~{download_gb:.1f} GB). "
            "This is a one-time download that persists across container restarts."
        )
        with (
            ui.card().classes("w-full bg-amber-50 border-l-4 border-amber-400 mb-4"),
            ui.row().classes("items-center gap-2"),
        ):
            ui.icon("warning").classes("text-amber-600")
            ui.label(dl_text).classes("text-sm text-amber-800")
    else:
        dl_text = (
            f"\u2139 First use will download the Whisper model (~{download_mb} MB). "
            "This is a one-time download."
        )
        with (
            ui.card().classes("w-full bg-blue-50 border-l-4 border-blue-400 mb-4"),
            ui.row().classes("items-center gap-2"),
        ):
            ui.icon("info").classes("text-blue-600")
            ui.label(dl_text).classes("text-sm text-blue-800")

    # --- Config summary ---
    async def _on_save() -> None:
        final = _resolve_final_config()
        api_key = config_state.get("api_key_value", "")
        keep_existing = config_state.get("keep_existing_key", False)
        if api_key and not keep_existing and final.llm.provider != LLMProvider.OLLAMA:
            valid_key, key_msg = await validate_api_key_live(final.llm.provider, api_key)
            if not valid_key:
                ui.notify(f"API key validation failed: {key_msg}", type="negative")
                return
            ui.notify(key_msg, type="positive")
        _complete_setup(final, container.settings.config_dir)

    summary_lines = build_config_summary(recommended)
    with ui.card().classes("w-full mb-4"):
        ui.label("Configuration Summary").classes("text-lg font-semibold mb-2")
        ui.separator()
        for line in summary_lines:
            ui.label(line).classes("text-sm font-mono mt-1")
        ui.label(
            "Note: saved config will reflect your Whisper model and LLM provider selections."
        ).classes("text-xs text-gray-400 mt-2 italic")

    # --- LLM provider validation ---
    provider_val = config_state.get("provider")
    preview_llm = recommend_config(
        config_state.get("has_gpu", False),
        config_state.get("vram_mb", 0),
        provider=LLMProvider(provider_val) if provider_val else None,
        llm_model=config_state.get("llm_model"),
        api_key_env=config_state.get("api_key_env"),
    ).llm
    valid, msg = validate_llm_provider(preview_llm)
    icon_name = "check_circle" if valid else "warning"
    css = "text-green-600" if valid else "text-amber-600"
    with ui.row().classes("items-center gap-2 mt-2"):
        ui.icon(icon_name).classes(f"text-lg {css}")
        ui.label(msg).classes(f"text-sm {css}")

    # --- Navigation ---
    with ui.row().classes("mt-4 gap-2"):
        ui.button("Back", on_click=stepper.previous)
        ui.button(
            "Save Configuration",
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
    app.storage.user[USER_HERMES_SETUP_COMPLETE] = True
    ui.notify("Lecture pipeline configured successfully!", type="positive")
    ui.navigate.to("/lectures")
    log.info("hermes_setup_complete", config=config.model_dump())
