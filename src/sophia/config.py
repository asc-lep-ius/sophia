"""Application settings via pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # FlareSolverr (optional, for scraping fallback)
    flaresolverr_url: str = "http://localhost:8191"

    # Calibre (optional, auto-detected)
    calibredb_path: str = "calibredb"

    # Typst (optional, auto-detected)
    typst_path: str = "typst"

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file."""
        return self.data_dir / "sophia.db"
