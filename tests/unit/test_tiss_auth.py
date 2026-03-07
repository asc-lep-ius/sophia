"""Tests for TISS authentication flow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from sophia.adapters.auth import (
    TissSessionCredentials,
    clear_tiss_session,
    load_tiss_session,
    save_tiss_session,
    tiss_session_path,
)


class TestTissSessionPath:
    def test_returns_expected_filename(self, tmp_path: Path):
        path = tiss_session_path(tmp_path)
        assert path.name == "tiss_session.json"
        assert path.parent == tmp_path


class TestTissSaveAndLoadSession:
    def test_roundtrip(self, tmp_path: Path):
        creds = TissSessionCredentials(
            jsessionid="JSID123",
            tiss_session="TISS_ABC",
            host="https://tiss.tuwien.ac.at",
            created_at=datetime.now(UTC).isoformat(),
        )
        path = tiss_session_path(tmp_path)
        save_tiss_session(creds, path)
        loaded = load_tiss_session(path)
        assert loaded is not None
        assert loaded.jsessionid == creds.jsessionid
        assert loaded.tiss_session == creds.tiss_session
        assert loaded.host == creds.host

    def test_creates_parent_directories(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "tiss_session.json"
        creds = TissSessionCredentials(
            jsessionid="J1",
            tiss_session="T1",
            host="https://tiss.tuwien.ac.at",
            created_at=datetime.now(UTC).isoformat(),
        )
        save_tiss_session(creds, path)
        assert path.exists()

    def test_restrictive_permissions(self, tmp_path: Path):
        creds = TissSessionCredentials(
            jsessionid="J1",
            tiss_session="T1",
            host="https://tiss.tuwien.ac.at",
            created_at=datetime.now(UTC).isoformat(),
        )
        path = tiss_session_path(tmp_path)
        save_tiss_session(creds, path)
        assert oct(path.stat().st_mode & 0o777) == "0o600"

    def test_load_missing_returns_none(self, tmp_path: Path):
        result = load_tiss_session(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_corrupt_returns_none(self, tmp_path: Path):
        path = tiss_session_path(tmp_path)
        path.write_text("not json at all")
        result = load_tiss_session(path)
        assert result is None

    def test_load_ignores_extra_fields(self, tmp_path: Path):
        path = tiss_session_path(tmp_path)
        data = {
            "jsessionid": "J1",
            "tiss_session": "T1",
            "host": "https://tiss.tuwien.ac.at",
            "created_at": "2026-01-01T00:00:00+00:00",
            "unknown_field": "should be ignored",
        }
        path.write_text(json.dumps(data))
        loaded = load_tiss_session(path)
        assert loaded is not None
        assert loaded.jsessionid == "J1"


class TestClearTissSession:
    def test_clears_existing(self, tmp_path: Path):
        path = tiss_session_path(tmp_path)
        path.write_text("{}")
        clear_tiss_session(path)
        assert not path.exists()

    def test_clears_missing_no_error(self, tmp_path: Path):
        clear_tiss_session(tmp_path / "nonexistent.json")
