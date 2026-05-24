"""Deterministic OpenAPI export tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export_openapi.py"


def test_openapi_export_is_deterministic(tmp_path: Path) -> None:
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"

    first_result = _run_export("--output", str(first_output))
    second_result = _run_export("--output", str(second_output))

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert first_output.read_bytes() == second_output.read_bytes()


def test_openapi_check_fails_on_drift_and_passes_after_regeneration(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"

    write_result = _run_export("--output", str(output))
    assert write_result.returncode == 0, write_result.stderr

    output.write_text('{"drifted": true}\n')
    drift_result = _run_export("--output", str(output), "--check")
    assert drift_result.returncode == 1
    assert "OpenAPI output is out of date" in drift_result.stderr

    rewrite_result = _run_export("--output", str(output))
    assert rewrite_result.returncode == 0, rewrite_result.stderr

    check_result = _run_export("--output", str(output), "--check")
    assert check_result.returncode == 0, check_result.stderr


def _run_export(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXPORT_SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
