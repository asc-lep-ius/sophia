"""Tests for TISS authentication flow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from bs4 import BeautifulSoup

from sophia.adapters.auth import (
    TissSessionCredentials,
    _build_auth_deltaspike_url,  # pyright: ignore[reportPrivateUsage]
    _extract_deltaspike_redirect,  # pyright: ignore[reportPrivateUsage]
    _extract_hidden_inputs,  # pyright: ignore[reportPrivateUsage]
    _extract_sesskey,  # pyright: ignore[reportPrivateUsage]
    _find_login_form,  # pyright: ignore[reportPrivateUsage]
    clear_tiss_session,
    load_tiss_session,
    save_tiss_session,
    tiss_session_path,
)
from sophia.domain.errors import AuthError


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


class TestExtractSesskey:
    def test_extracts_sesskey(self):
        html = '<script>var M = {"sesskey":"abc123XYZ"};</script>'
        assert _extract_sesskey(html) == "abc123XYZ"  # pyright: ignore[reportPrivateUsage]

    def test_extracts_with_spaces(self):
        html = '"sesskey" : "key42"'
        assert _extract_sesskey(html) == "key42"  # pyright: ignore[reportPrivateUsage]

    def test_raises_when_missing(self):
        with pytest.raises(AuthError, match="sesskey not found"):
            _extract_sesskey("<html>no key here</html>")  # pyright: ignore[reportPrivateUsage]


class TestFindLoginForm:
    def test_finds_form(self):
        html = '<form id="login"><input name="username"/><input name="password"/></form>'
        soup = BeautifulSoup(html, "lxml")
        form = _find_login_form(soup)  # pyright: ignore[reportPrivateUsage]
        assert form.get("id") == "login"

    def test_raises_no_username_input(self):
        soup = BeautifulSoup("<form><input name='email'/></form>", "lxml")
        with pytest.raises(AuthError, match="login form not found"):
            _find_login_form(soup)  # pyright: ignore[reportPrivateUsage]

    def test_raises_no_parent_form(self):
        soup = BeautifulSoup("<div><input name='username'/></div>", "lxml")
        with pytest.raises(AuthError, match="no parent form"):
            _find_login_form(soup)  # pyright: ignore[reportPrivateUsage]


class TestExtractHiddenInputs:
    def test_collects_hidden_fields(self):
        html = (
            "<form>"
            '<input type="hidden" name="csrf" value="tok1"/>'
            '<input type="hidden" name="relay" value="tok2"/>'
            '<input type="text" name="user" value="ignored"/>'
            "</form>"
        )
        soup = BeautifulSoup(html, "lxml")
        form = soup.find("form")
        assert form is not None
        result = _extract_hidden_inputs(form)  # pyright: ignore[reportPrivateUsage]
        assert result == {"csrf": "tok1", "relay": "tok2"}

    def test_skips_nameless_inputs(self):
        html = '<form><input type="hidden" value="ghost"/></form>'
        soup = BeautifulSoup(html, "lxml")
        form = soup.find("form")
        assert form is not None
        assert _extract_hidden_inputs(form) == {}  # pyright: ignore[reportPrivateUsage]


class TestExtractDeltaspikeRedirectAuth:
    def test_returns_redirect_url(self):
        html = (
            "<html><head><title>Loading</title></head><body>"
            "<script>var redirectUrl = '/education/favorites.xhtml?x=1';</script>"
            "</body></html>"
        )
        soup = BeautifulSoup(html, "lxml")
        url = _extract_deltaspike_redirect(soup)  # pyright: ignore[reportPrivateUsage]
        assert url == "/education/favorites.xhtml?x=1"

    def test_returns_none_without_loading_title(self):
        html = "<html><head><title>Dashboard</title></head><body></body></html>"
        soup = BeautifulSoup(html, "lxml")
        assert _extract_deltaspike_redirect(soup) is None  # pyright: ignore[reportPrivateUsage]

    def test_returns_none_without_title(self):
        soup = BeautifulSoup("<html><body></body></html>", "lxml")
        assert _extract_deltaspike_redirect(soup) is None  # pyright: ignore[reportPrivateUsage]

    def test_returns_none_when_no_script_match(self):
        html = (
            "<html><head><title>Loading</title></head><body>"
            "<script>var other = 'value';</script>"
            "</body></html>"
        )
        soup = BeautifulSoup(html, "lxml")
        assert _extract_deltaspike_redirect(soup) is None  # pyright: ignore[reportPrivateUsage]


class TestBuildAuthDeltaspikeUrl:
    def test_adds_dsrid_dswid(self):
        async def _run():
            async with httpx.AsyncClient() as client:
                url = _build_auth_deltaspike_url(  # pyright: ignore[reportPrivateUsage]
                    "https://tiss.tuwien.ac.at/education/favorites.xhtml",
                    "/education/favorites.xhtml?x=1",
                    client,
                )
                parsed = httpx.URL(url)
                assert "dsrid" in str(parsed.params)
                assert "dswid" in str(parsed.params)
                assert parsed.scheme == "https"

        import asyncio

        asyncio.run(_run())
