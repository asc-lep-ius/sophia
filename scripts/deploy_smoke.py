"""Run production post-deploy HTTP smoke checks."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from http.client import HTTPResponse

DEFAULT_READY_PATH: Final = "/api/ready"
DEFAULT_APP_PATH: Final = "/app/"
DEFAULT_SSE_PATH: Final = "/api/events"
DEFAULT_CONNECT_TIMEOUT_SECONDS: Final = 10.0
DEFAULT_FIRST_EVENT_TIMEOUT_SECONDS: Final = 2.0
MAX_BODY_BYTES: Final = 1024 * 1024
MAX_SSE_LINE_BYTES: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class SmokeConfig:
    base_url: str
    ready_path: str = DEFAULT_READY_PATH
    app_path: str = DEFAULT_APP_PATH
    sse_path: str = DEFAULT_SSE_PATH
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    first_event_timeout_seconds: float = DEFAULT_FIRST_EVENT_TIMEOUT_SECONDS


class SmokeCheckError(RuntimeError):
    """A deploy smoke check failed."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Public production origin to smoke.")
    parser.add_argument("--ready-path", default=DEFAULT_READY_PATH)
    parser.add_argument("--app-path", default=DEFAULT_APP_PATH)
    parser.add_argument("--sse-path", default=DEFAULT_SSE_PATH)
    parser.add_argument("--connect-timeout", type=float, default=DEFAULT_CONNECT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--first-event-timeout",
        type=float,
        default=DEFAULT_FIRST_EVENT_TIMEOUT_SECONDS,
    )
    args = parser.parse_args(argv)

    config = SmokeConfig(
        base_url=args.base_url,
        ready_path=args.ready_path,
        app_path=args.app_path,
        sse_path=args.sse_path,
        connect_timeout_seconds=args.connect_timeout,
        first_event_timeout_seconds=args.first_event_timeout,
    )
    try:
        messages = run_smoke(config)
    except SmokeCheckError as exc:
        sys.stderr.write(f"deploy smoke failed: {exc}\n")
        return 1

    for message in messages:
        sys.stdout.write(f"{message}\n")
    return 0


def run_smoke(config: SmokeConfig) -> list[str]:
    return [
        _check_ready(config),
        _check_app(config),
        _check_sse(config),
    ]


def _check_ready(config: SmokeConfig) -> str:
    url = _build_url(config.base_url, config.ready_path)
    response = _open_url(url, timeout=config.connect_timeout_seconds)
    try:
        _require_success(response, url)
        payload = _read_json(response, url)
    finally:
        response.close()

    if payload.get("status") != "ready":
        raise SmokeCheckError(f"{url} did not report ready status")
    return f"ready ok: {config.ready_path}"


def _check_app(config: SmokeConfig) -> str:
    url = _build_url(config.base_url, config.app_path)
    response = _open_url(url, timeout=config.connect_timeout_seconds)
    try:
        _require_success(response, url)
        content_type = _content_type(response)
    finally:
        response.close()

    if "text/html" not in content_type:
        raise SmokeCheckError(
            f"{url} returned {content_type or 'no content type'}, expected text/html"
        )
    return f"app ok: {config.app_path}"


def _check_sse(config: SmokeConfig) -> str:
    url = _build_url(config.base_url, config.sse_path)
    response = _open_url(
        url,
        headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
        timeout=config.connect_timeout_seconds,
    )
    try:
        _require_success(response, url)
        content_type = _content_type(response)
        if "text/event-stream" not in content_type:
            raise SmokeCheckError(
                f"{url} returned {content_type or 'no content type'}, expected text/event-stream"
            )
        _read_first_sse_event(response, url, timeout=config.first_event_timeout_seconds)
    finally:
        response.close()
    return f"sse ok: {config.sse_path}"


def _open_url(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> HTTPResponse:
    request = Request(url, headers=headers or {})
    try:
        return cast("HTTPResponse", urlopen(request, timeout=timeout))
    except HTTPError as exc:
        raise SmokeCheckError(f"{url} returned HTTP {exc.code}") from exc
    except TimeoutError as exc:
        raise SmokeCheckError(f"{url} timed out after {timeout:.1f}s") from exc
    except URLError as exc:
        raise SmokeCheckError(f"{url} could not be reached: {exc.reason}") from exc


def _require_success(response: HTTPResponse, url: str) -> None:
    if not 200 <= response.status < 300:
        raise SmokeCheckError(f"{url} returned HTTP {response.status}")


def _read_json(response: HTTPResponse, url: str) -> dict[str, Any]:
    body = response.read(MAX_BODY_BYTES)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SmokeCheckError(f"{url} did not return valid JSON") from exc
    if not isinstance(payload, dict):
        raise SmokeCheckError(f"{url} returned non-object JSON")
    return cast("dict[str, Any]", payload)


def _read_first_sse_event(response: HTTPResponse, url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    event_lines: list[str] = []

    while time.monotonic() < deadline:
        try:
            raw_line = response.readline(MAX_SSE_LINE_BYTES)
        except TimeoutError as exc:
            raise SmokeCheckError(f"{url} did not emit an SSE event within {timeout:.1f}s") from exc

        if raw_line == b"":
            break

        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            if _contains_sse_payload(event_lines):
                return
            event_lines.clear()
            continue
        if not line.startswith(":"):
            event_lines.append(line)

    raise SmokeCheckError(f"{url} did not emit an SSE event within {timeout:.1f}s")


def _contains_sse_payload(lines: list[str]) -> bool:
    return any(line.startswith("event:") or line.startswith("data:") for line in lines)


def _content_type(response: HTTPResponse) -> str:
    return response.headers.get("Content-Type", "").lower()


def _build_url(base_url: str, path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return urljoin(base_url.rstrip("/") + "/", normalized_path.lstrip("/"))


if __name__ == "__main__":
    raise SystemExit(main())
