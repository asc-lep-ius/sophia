"""Blocking-I/O audit tests for async API routers."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "blocking_audit.py"


def test_blocking_audit_passes_phase_one_routers() -> None:
    result = _run_audit("--check")

    assert result.returncode == 0, result.stderr


def test_blocking_audit_catches_unwrapped_sync_io_in_async_router(tmp_path: Path) -> None:
    routers_dir = tmp_path / "src" / "sophia" / "api" / "routers"
    routers_dir.mkdir(parents=True)
    (routers_dir / "bad.py").write_text(
        textwrap.dedent(
            """
            from pathlib import Path

            from fastapi import APIRouter

            router = APIRouter()


            @router.get('/bad')
            async def bad_route() -> dict[str, str]:
                return {'content': Path('payload.txt').read_text()}
            """
        )
    )

    result = _run_audit("--root", str(tmp_path), "--check")

    assert result.returncode == 1
    assert "Path.read_text" in result.stderr
    assert "anyio.to_thread.run_sync" in result.stderr


def test_blocking_audit_allows_thread_wrapped_sync_io(tmp_path: Path) -> None:
    routers_dir = tmp_path / "src" / "sophia" / "api" / "routers"
    routers_dir.mkdir(parents=True)
    (routers_dir / "good.py").write_text(
        textwrap.dedent(
            """
            from pathlib import Path

            import anyio
            from fastapi import APIRouter

            router = APIRouter()


            @router.get('/good')
            async def good_route() -> dict[str, str]:
                content = await anyio.to_thread.run_sync(Path('payload.txt').read_text)
                return {'content': content}
            """
        )
    )

    result = _run_audit("--root", str(tmp_path), "--check")

    assert result.returncode == 0, result.stderr


def _run_audit(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
