"""Proxy configuration regression tests."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_project_file(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def active_caddy_lines(caddyfile: str) -> list[str]:
    return [
        line.split("#", 1)[0].strip()
        for line in caddyfile.splitlines()
        if line.split("#", 1)[0].strip()
    ]


def caddy_block(caddyfile: str, marker: str) -> str:
    block_start = caddyfile.index(marker)
    opening_brace = caddyfile.index("{", block_start)
    depth = 0

    for offset, char in enumerate(caddyfile[opening_brace:], start=opening_brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return caddyfile[block_start : offset + 1]

    raise AssertionError(f"Caddy block {marker!r} was not closed")


def compose_service_block(compose_file: str, service_name: str) -> str:
    services_start = compose_file.index("services:\n")
    service_match = re.search(
        rf"^  {re.escape(service_name)}:\n",
        compose_file[services_start:],
        flags=re.MULTILINE,
    )

    assert service_match is not None, f"compose service {service_name!r} not found"

    service_start = services_start + service_match.start()
    next_service = re.search(
        r"^  [A-Za-z0-9_.-]+:\n",
        compose_file[service_start + 1 :],
        flags=re.MULTILINE,
    )
    service_end = len(compose_file)

    if next_service is not None:
        service_end = service_start + 1 + next_service.start()

    return compose_file[service_start:service_end]


def compose_environment(service_block: str) -> dict[str, str]:
    environment_header = "\n    environment:\n"
    environment_start = service_block.index(environment_header)
    environment_lines = service_block[environment_start + len(environment_header) :].splitlines()
    environment: dict[str, str] = {}

    for line in environment_lines:
        if not line.startswith("      "):
            break

        entry = line.strip()
        if entry.startswith("- "):
            key, _, value = entry[2:].partition("=")
        else:
            key, _, value = entry.partition(":")

        environment[key.strip()] = value.strip().strip('"')

    return environment


def test_caddy_routes_app_api_and_legacy_before_fallback() -> None:
    caddyfile = read_project_file("proxy/Caddyfile")
    exact_app_redirect = "\tredir /app /app/ 308"
    frontend_app_handle = "\thandle /app/* {"
    api_sse_handle = "\thandle @api_sse {"
    api_handle = "\thandle /api/* {"
    legacy_redirect = "\tredir /legacy /legacy/ 308"
    legacy_handle = "\thandle_path /legacy/* {"
    legacy_fallback = "\thandle {"

    assert exact_app_redirect in caddyfile
    assert caddyfile.index(exact_app_redirect) < caddyfile.index(frontend_app_handle)
    assert caddyfile.index(frontend_app_handle) < caddyfile.index(legacy_fallback)
    assert caddyfile.index(api_sse_handle) < caddyfile.index(api_handle)
    assert caddyfile.index(api_handle) < caddyfile.index(legacy_fallback)
    assert caddyfile.index(legacy_redirect) < caddyfile.index(legacy_handle)
    assert caddyfile.index(legacy_handle) < caddyfile.index(legacy_fallback)


def test_caddy_sse_streams_are_not_buffered_or_compressed() -> None:
    caddyfile = read_project_file("proxy/Caddyfile")
    sse_block = caddy_block(caddyfile, "\thandle @api_sse")
    active_lines = active_caddy_lines(caddyfile)

    assert "flush_interval -1" in sse_block
    assert "transport http" in sse_block
    assert "compression off" in sse_block
    assert not any(line == "encode" or line.startswith("encode ") for line in active_lines)


def test_caddy_rate_limit_is_only_a_documented_placeholder() -> None:
    caddyfile = read_project_file("proxy/Caddyfile")
    active_lines = active_caddy_lines(caddyfile)

    assert "Caddy core has no built-in" in caddyfile
    assert not any(line == "rate_limit" or line.startswith("rate_limit ") for line in active_lines)


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_frontend_forwards_sveltekit_proxy_headers(compose_path: str) -> None:
    compose_file = read_project_file(compose_path)
    frontend_environment = compose_environment(compose_service_block(compose_file, "frontend"))

    assert frontend_environment["PROTOCOL_HEADER"] == "x-forwarded-proto"
    assert frontend_environment["HOST_HEADER"] == "x-forwarded-host"
