"""Application settings via pydantic-settings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Self

from platformdirs import user_cache_dir, user_config_dir, user_data_dir
from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_DEVELOPMENT_SECRET_KEY = "sophia-local-development-secret-key"
_MINIMUM_PRODUCTION_SECRET_KEY_BYTES = 32
_DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 8
_COOKIE_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


class Settings(BaseSettings):
    """Sophia configuration — loaded from environment and .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="SOPHIA_", extra="ignore")

    # TUWEL / TISS
    tuwel_host: str = "https://tuwel.tuwien.ac.at"
    tiss_host: str = "https://tiss.tuwien.ac.at"

    # Anna's Archive
    annas_api_key: str = ""
    annas_mirrors: list[str] = ["annas-archive.li", "annas-archive.se"]

    # LLM (optional)
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # Directories (XDG-compliant defaults, lazily evaluated)
    download_dir: Path = Field(default_factory=lambda: Path.home() / "Downloads" / "sophia")
    data_dir: Path = Field(default_factory=lambda: Path(user_data_dir("sophia")))
    config_dir: Path = Field(default_factory=lambda: Path(user_config_dir("sophia")))
    cache_dir: Path = Field(default_factory=lambda: Path(user_cache_dir("sophia")))

    # Downloads
    preferred_formats: list[str] = ["pdf", "epub"]
    max_concurrent_downloads: int = 2
    max_download_size_bytes: int = 5 * 1024**3  # 5 GB

    # FlareSolverr (optional, for scraping fallback)
    flaresolverr_url: str = "http://localhost:8191"

    # Calibre (optional, auto-detected)
    calibredb_path: str = "calibredb"

    # Typst (optional, auto-detected)
    typst_path: str = "typst"

    # GUI
    gui_host: str = "127.0.0.1"
    gui_port: int = 8080
    gui_reload: bool = False
    auto_sync: bool = True

    # API/session security
    production: bool = False
    secret_key: str = ""
    secret_key_current: str = ""
    secret_key_previous: str = ""
    redis_url: str = "redis://localhost:6379/0"
    session_cookie_name: str = "__Host-sophia_session"
    csrf_cookie_name: str = "__Host-sophia_csrf"
    session_ttl_seconds: int = _DEFAULT_SESSION_TTL_SECONDS
    session_cookie_secure: bool = True
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # Session health
    session_keepalive_interval: int = 300

    # Persistence
    database_url: str = "postgresql+asyncpg://sophia:sophia@localhost:5432/sophia"
    database_pool_size: int = Field(default=5, gt=0)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout: int = Field(default=30, gt=0)
    database_pool_recycle: int = Field(default=1800, gt=0)
    database_echo: bool = False

    # Learning process integrity
    default_content_language: Literal["de", "en"] = "de"
    learning_event_retention_days: int = Field(default=180, gt=0)
    learning_event_max_future_skew_seconds: int = Field(default=60, ge=0)
    elaboration_min_chars: int = Field(default=80, ge=0)
    elaboration_min_prompt_dwell_ms: int = Field(default=5000, ge=0)
    # The reflection floor the CLI has always paced at, made a setting so the
    # web surface reads it from the server rather than hard-coding a number a
    # client-side edit could shorten.
    study_reflection_min_seconds: int = Field(default=30, ge=0)

    # Study realtime (SSE)
    sse_heartbeat_interval_seconds: int = Field(default=15, gt=0)
    sse_event_retention_days: int = Field(default=3, gt=0)
    sse_max_streams_per_user: int = Field(default=4, gt=0)
    sse_queue_maxsize: int = Field(default=64, gt=0)
    sse_replay_batch_size: int = Field(default=200, gt=0)

    # Observability
    log_format: Literal["json", "console"] = "json"
    log_debug: bool = False
    sentry_dsn: str = ""
    sentry_release: str = ""
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("session_keepalive_interval")
    @classmethod
    def _keepalive_at_least_60(cls, value: int) -> int:
        if value < 60:
            msg = "session_keepalive_interval must be at least 60 seconds"
            raise ValueError(msg)
        return value

    @field_validator("redis_url")
    @classmethod
    def _redis_url_uses_supported_scheme(cls, value: str) -> str:
        redis_url = value.strip()
        if not redis_url:
            msg = "redis_url must not be empty"
            raise ValueError(msg)
        scheme = redis_url.split(":", 1)[0]
        if scheme not in {"redis", "rediss", "unix"}:
            msg = "redis_url must use redis://, rediss://, or unix://"
            raise ValueError(msg)
        return redis_url

    @field_validator("database_url")
    @classmethod
    def _database_url_uses_async_driver(cls, value: str) -> str:
        """Reject the sync driver early.

        ``postgresql://`` resolves to psycopg and blocks the event loop on every
        query. It fails at first use, deep inside a request, rather than at
        startup — so it is worth catching here.
        """
        database_url = value.strip()
        if not database_url:
            msg = "database_url must not be empty"
            raise ValueError(msg)
        if not database_url.startswith("postgresql+asyncpg://"):
            msg = "database_url must use the postgresql+asyncpg:// driver"
            raise ValueError(msg)
        return database_url

    @field_validator("session_cookie_name", "csrf_cookie_name")
    @classmethod
    def _cookie_name_is_valid(cls, value: str, info: ValidationInfo) -> str:
        cookie_name = value.strip()
        if not cookie_name or _COOKIE_NAME_PATTERN.fullmatch(cookie_name) is None:
            msg = f"{info.field_name} must be a valid cookie name"
            raise ValueError(msg)
        return cookie_name

    @field_validator("session_ttl_seconds")
    @classmethod
    def _session_ttl_at_least_60(cls, value: int) -> int:
        if value < 60:
            msg = "session_ttl_seconds must be at least 60 seconds"
            raise ValueError(msg)
        return value

    @field_validator("session_cookie_samesite", mode="before")
    @classmethod
    def _normalize_session_cookie_samesite(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @model_validator(mode="after")
    def _validate_production_secret_key(self) -> Self:
        self.validate_secret_key_configuration()
        self.validate_session_cookie_configuration()
        return self

    def ensure_dirs(self) -> None:
        """Create application directories with restrictive permissions."""
        for d in (self.data_dir, self.config_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True, mode=0o700)

    def validate_secret_key_configuration(self) -> None:
        """Fail fast when production lacks a valid current signing key."""
        if not self.production:
            return

        if not self.secret_key_current:
            msg = "SOPHIA_SECRET_KEY_CURRENT is required in production"
            raise ValueError(msg)

        if len(self.secret_key_current.encode()) < _MINIMUM_PRODUCTION_SECRET_KEY_BYTES:
            msg = "SOPHIA_SECRET_KEY_CURRENT must be at least 32 bytes/characters long"
            raise ValueError(msg)

    def validate_session_cookie_configuration(self) -> None:
        """Fail fast on cookie settings that browsers would reject or weaken."""
        if self.production and not self.session_cookie_secure:
            msg = "session_cookie_secure must be enabled in production"
            raise ValueError(msg)

        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            msg = "session_cookie_secure must be enabled when SameSite=None"
            raise ValueError(msg)

        host_prefixed_names = (
            self.session_cookie_name.startswith("__Host-"),
            self.csrf_cookie_name.startswith("__Host-"),
        )
        if any(host_prefixed_names) and not self.session_cookie_secure:
            msg = "__Host- session cookies require session_cookie_secure=true"
            raise ValueError(msg)

    def session_signing_key(self) -> str:
        """Return the active signing key, with a local-only development fallback."""
        if self.secret_key_current:
            return self.secret_key_current
        if self.production:
            self.validate_secret_key_configuration()
        if self.secret_key:
            return self.secret_key
        return _LOCAL_DEVELOPMENT_SECRET_KEY

    def nicegui_storage_secret(self) -> str:
        """Return the secret used by NiceGUI browser-backed storage."""
        return self.session_signing_key()

    def session_verification_keys(self) -> tuple[str, ...]:
        """Return unique keys accepted for session verification."""
        keys = [self.session_signing_key()]
        for candidate in (self.secret_key_previous, self.secret_key):
            if candidate and candidate not in keys:
                keys.append(candidate)
        return tuple(keys)
