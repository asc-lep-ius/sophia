"""The e2e marker must not reach beyond the integration suite.

`tests/integration/gui/conftest.py` marks items for the whole session, so an
over-broad match there silently deselects unrelated tests from every default
run: they neither pass nor fail, they simply never execute.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
INTEGRATION_PREFIX = "tests/integration/"


def test_e2e_marker_is_confined_to_the_integration_suite() -> None:
    marked_paths = _collected_paths("e2e")

    assert marked_paths, "expected the integration suite to be marked e2e"
    assert all(path.startswith(INTEGRATION_PREFIX) for path in sorted(marked_paths))


def test_default_run_selects_every_non_integration_test() -> None:
    selected_paths = _collected_paths("not e2e")

    assert "tests/api/test_integrations_tiss.py" in selected_paths
    assert not any(path.startswith(INTEGRATION_PREFIX) for path in sorted(selected_paths))


def _collected_paths(marker_expression: str) -> set[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-m",
            marker_expression,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {
        line.split("::", 1)[0]
        for line in result.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    }
