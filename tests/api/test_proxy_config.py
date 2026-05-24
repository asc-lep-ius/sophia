"""Proxy configuration regression tests."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_caddy_redirects_exact_app_before_legacy_fallback() -> None:
    caddyfile = (PROJECT_ROOT / "proxy" / "Caddyfile").read_text(encoding="utf-8")
    exact_app_redirect = "\tredir /app /app/ 308"
    frontend_app_handle = "\thandle /app/* {"
    legacy_fallback = "\thandle {"

    assert exact_app_redirect in caddyfile
    assert caddyfile.index(exact_app_redirect) < caddyfile.index(frontend_app_handle)
    assert caddyfile.index(frontend_app_handle) < caddyfile.index(legacy_fallback)
