"""Post-deploy smoke script tests."""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).parents[2]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "deploy_smoke.py"


class SmokeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/api/ready":
            self._send_response(
                b'{"status":"ready","checks":[]}',
                content_type="application/json",
            )
            return
        if self.path == "/app/":
            self._send_response(b"<!doctype html><html></html>", content_type="text/html")
            return
        if self.path == "/api/events":
            self._send_response(
                b'event: ready\ndata: {"status":"ready"}\n\n',
                content_type="text/event-stream",
            )
            return

        self.send_error(404)

    def log_message(self, format: str, *_args: object) -> None:
        return

    def _send_response(self, body: bytes, *, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


class BrokenSseHandler(SmokeHandler):
    def do_GET(self) -> None:
        if self.path == "/api/events":
            self._send_response(b"hello\n", content_type="text/plain")
            return

        super().do_GET()


def test_deploy_smoke_passes_ready_app_and_sse_checks() -> None:
    with smoke_server(SmokeHandler) as base_url:
        result = _run_smoke(base_url)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "ready ok: /api/ready",
        "app ok: /app/",
        "sse ok: /api/events",
    ]


def test_deploy_smoke_fails_when_sse_is_not_event_stream() -> None:
    with smoke_server(BrokenSseHandler) as base_url:
        result = _run_smoke(base_url)

    assert result.returncode == 1
    assert "expected text/event-stream" in result.stderr


@contextmanager
def smoke_server(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    host, port = cast("tuple[str, int]", server.server_address)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _run_smoke(base_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT), "--base-url", base_url],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
