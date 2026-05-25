"""Proxy configuration regression tests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_project_file(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def read_compose_file(path: str) -> dict[str, Any]:
    compose = yaml.safe_load(read_project_file(path))
    assert isinstance(compose, dict)
    return compose


def compose_services(compose_path: str) -> dict[str, Any]:
    services = read_compose_file(compose_path)["services"]
    assert isinstance(services, dict)
    return services


def compose_config_environment(service_config: dict[str, Any]) -> dict[str, str]:
    environment = service_config.get("environment", {})

    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}

    if isinstance(environment, list):
        parsed_environment: dict[str, str] = {}
        for entry in environment:
            key, _, value = str(entry).partition("=")
            parsed_environment[key] = value
        return parsed_environment

    return {}


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
    assert "stream_close_delay 5m" in sse_block
    assert "transport http" in sse_block
    assert "compression off" in sse_block
    assert not any(line == "encode" or line.startswith("encode ") for line in active_lines)
    assert sse_block.index("flush_interval -1") < sse_block.index("stream_close_delay 5m")
    assert sse_block.index("stream_close_delay 5m") < sse_block.index("transport http")


def test_caddy_rate_limit_is_active_for_login_per_ip() -> None:
    caddyfile = read_project_file("proxy/Caddyfile")
    rate_limit_block = caddy_block(caddyfile, "\trate_limit")

    assert "order rate_limit before reverse_proxy" in caddyfile
    assert "zone login_per_ip" in rate_limit_block
    assert "method POST" in rate_limit_block
    assert "path /api/auth/login /api/auth/login/" in rate_limit_block
    assert "key {remote_host}" in rate_limit_block
    assert "events 5" in rate_limit_block
    assert "window 1m" in rate_limit_block
    assert "ipv6_prefix 64" in rate_limit_block
    assert "jitter 10" in rate_limit_block


def test_caddy_rate_limit_is_scoped_to_login_posts_only() -> None:
    caddyfile = read_project_file("proxy/Caddyfile")
    rate_limit_block = caddy_block(caddyfile, "\trate_limit")

    assert caddyfile.index("\trate_limit") < caddyfile.index("\thandle /api/*")
    assert "path /api/auth/login /api/auth/login/" in rate_limit_block
    assert "path /api/*" not in rate_limit_block
    assert "method POST" in rate_limit_block
    assert "method GET" not in rate_limit_block


def test_proxy_dockerfile_builds_pinned_rate_limit_plugin() -> None:
    dockerfile = read_project_file("proxy/Dockerfile")
    builder_stage_start = dockerfile.index("FROM caddy:${CADDY_VERSION}-builder AS builder")
    runtime_stage_start = dockerfile.index("FROM caddy:${CADDY_VERSION}", builder_stage_start + 1)
    builder_stage = dockerfile[builder_stage_start:runtime_stage_start]
    custom_binary_copy = "COPY --from=builder /usr/bin/caddy /usr/bin/caddy"
    caddyfile_copy = "COPY Caddyfile /etc/caddy/Caddyfile"
    caddyfile_validation = (
        "RUN /usr/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile"
    )
    caddyfile_adapt = (
        "RUN /usr/bin/caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile "
        "--pretty > /tmp/Caddyfile.json"
    )

    assert "ARG CADDY_VERSION=2.11.3" in dockerfile
    assert "ARG XCADDY_VERSION=v0.4.5" in dockerfile
    assert re.search(r"ARG RATELIMIT_VERSION=[0-9a-f]{40}", dockerfile) is not None
    assert "FROM caddy:${CADDY_VERSION}-builder AS builder" in dockerfile
    assert "ARG CADDY_VERSION" in builder_stage
    assert "ARG XCADDY_VERSION" in builder_stage
    assert "ARG RATELIMIT_VERSION" in builder_stage
    assert "github.com/caddyserver/xcaddy/cmd/xcaddy@${XCADDY_VERSION}" in builder_stage
    assert 'caddy_version="${CADDY_VERSION#v}"' in builder_stage
    assert '/go/bin/xcaddy build "v${caddy_version}"' in builder_stage
    assert "--with github.com/mholt/caddy-ratelimit@${RATELIMIT_VERSION}" in builder_stage
    assert custom_binary_copy in dockerfile
    assert caddyfile_copy in dockerfile
    assert caddyfile_validation in dockerfile
    assert caddyfile_adapt in dockerfile
    assert dockerfile.index(custom_binary_copy) < dockerfile.index(caddyfile_copy)
    assert dockerfile.index(caddyfile_copy) < dockerfile.index(caddyfile_validation)
    assert dockerfile.index(caddyfile_validation) < dockerfile.index(caddyfile_adapt)
    assert "xcaddy build vv" not in dockerfile
    assert "xcaddy build v${CADDY_VERSION}" not in dockerfile
    assert "@latest" not in dockerfile


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_frontend_forwards_sveltekit_proxy_headers(compose_path: str) -> None:
    compose_file = read_project_file(compose_path)
    frontend_environment = compose_environment(compose_service_block(compose_file, "frontend"))

    assert frontend_environment["PROTOCOL_HEADER"] == "x-forwarded-proto"
    assert frontend_environment["HOST_HEADER"] == "x-forwarded-host"


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_compose_keeps_runtime_topology_split(compose_path: str) -> None:
    services = compose_services(compose_path)
    api_environment = compose_config_environment(services["api"])

    assert {"proxy", "frontend", "api", "redis", "sophia-gui"} <= set(services)
    assert "ports" not in services["frontend"]
    assert "ports" not in services["api"]
    assert "ports" not in services["redis"]
    assert "sophia.api.app:create_standalone_api_app" in services["api"].get("command", [])
    assert api_environment["SOPHIA_REDIS_URL"] == "redis://redis:6379/0"
    assert services["api"]["depends_on"]["redis"]["condition"] == "service_healthy"
    assert {"frontend", "api", "sophia-gui"} <= set(services["proxy"]["depends_on"])
