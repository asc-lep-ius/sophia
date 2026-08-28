"""Secret-literal policy tests."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
POLICY_SCRIPT = REPO_ROOT / "scripts" / "secret_policy.py"


def test_secret_policy_passes_repository() -> None:
    result = _run_policy(REPO_ROOT)

    assert result.returncode == 0, result.stderr


def test_secret_policy_catches_python_storage_secret_literal(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "sophia" / "gui"
    source_dir.mkdir(parents=True)
    (source_dir / "app.py").write_text(
        textwrap.dedent(
            """
            from nicegui import ui


            def run() -> None:
                ui.run(storage_secret="hard-coded-gui-storage-secret")
            """
        )
    )

    result = _run_policy(tmp_path)

    assert result.returncode == 1
    assert "src/sophia/gui/app.py" in result.stderr
    assert "storage_secret" in result.stderr


def test_secret_policy_catches_python_secret_key_literal(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "sophia"
    source_dir.mkdir(parents=True)
    (source_dir / "config.py").write_text(
        'SOPHIA_SECRET_KEY_CURRENT = "hard-coded-production-secret-key"\n'
    )

    result = _run_policy(tmp_path)

    assert result.returncode == 1
    assert "SOPHIA_SECRET_KEY_CURRENT" in result.stderr


def test_secret_policy_catches_python_secret_dict_key_literal(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "sophia"
    source_dir.mkdir(parents=True)
    (source_dir / "settings.py").write_text(
        textwrap.dedent(
            """
            CONFIG = {
                "SOPHIA_SECRET_KEY_CURRENT": "hard-coded-production-secret-key",
            }
            """
        )
    )

    result = _run_policy(tmp_path)

    assert result.returncode == 1
    assert "src/sophia/settings.py:3" in result.stderr
    assert "SOPHIA_SECRET_KEY_CURRENT" in result.stderr


def test_secret_policy_catches_python_secret_subscript_assignment(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "sophia"
    source_dir.mkdir(parents=True)
    (source_dir / "runtime.py").write_text(
        textwrap.dedent(
            """
            import os

            os.environ["SOPHIA_SECRET_KEY_CURRENT"] = "hard-coded-production-secret-key"
            """
        )
    )

    result = _run_policy(tmp_path)

    assert result.returncode == 1
    assert "src/sophia/runtime.py:4" in result.stderr
    assert "SOPHIA_SECRET_KEY_CURRENT" in result.stderr


def test_secret_policy_flags_safe_marker_substrings_in_source_literals(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "sophia"
    source_dir.mkdir(parents=True)
    (source_dir / "settings.py").write_text(
        'SOPHIA_SECRET_KEY_CURRENT = "production-test-secret-key-that-is-unsafe"\n'
    )

    result = _run_policy(tmp_path)

    assert result.returncode == 1
    assert "SOPHIA_SECRET_KEY_CURRENT" in result.stderr


def test_secret_policy_uses_scan_root_relative_test_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "tests" / "repo"
    source_dir = repo_root / "src" / "sophia"
    source_dir.mkdir(parents=True)
    (source_dir / "settings.py").write_text(
        'SOPHIA_SECRET_KEY_CURRENT = "production-test-secret-key-that-is-unsafe"\n'
    )

    result = _run_policy(repo_root)

    assert result.returncode == 1
    assert "src/sophia/settings.py:1" in result.stderr
    assert "SOPHIA_SECRET_KEY_CURRENT" in result.stderr


@pytest.mark.parametrize(
    "relative_path",
    [
        Path("src/sophia/tests/test_fixture.py"),
        Path("src/sophia/test_settings.py"),
    ],
)
def test_secret_policy_allows_test_markers_in_repo_relative_test_paths(
    tmp_path: Path,
    relative_path: Path,
) -> None:
    secret_file = tmp_path / relative_path
    secret_file.parent.mkdir(parents=True)
    secret_file.write_text('storage_secret="explicit-test-fixture-secret"\n')

    result = _run_policy(tmp_path)

    assert result.returncode == 0, result.stderr


def test_secret_policy_catches_compose_and_dockerfile_literals(tmp_path: Path) -> None:
    ci_dir = tmp_path / "ci"
    ci_dir.mkdir()
    (tmp_path / "docker-compose.prod.yml").write_text(
        textwrap.dedent(
            """
            services:
              api:
                environment:
                  SOPHIA_SECRET_KEY_CURRENT: hard-coded-production-secret-key
            """
        )
    )
    (tmp_path / "Dockerfile").write_text(
        "ENV SOPHIA_SECRET_KEY_CURRENT=hard-coded-production-secret-key\n"
    )
    (ci_dir / "Dockerfile.ci").write_text(
        "ARG SOPHIA_SECRET_KEY_CURRENT=hard-coded-production-secret-key\n"
    )

    result = _run_policy(tmp_path)

    assert result.returncode == 1
    assert result.stderr.index("Dockerfile:1") < result.stderr.index("ci/Dockerfile.ci")
    assert result.stderr.index("ci/Dockerfile.ci") < result.stderr.index("docker-compose.prod.yml")


def test_secret_policy_catches_ci_and_proxy_dockerfile_literals(tmp_path: Path) -> None:
    proxy_dir = tmp_path / "proxy"
    proxy_dir.mkdir()
    (tmp_path / ".gitlab-ci.yml").write_text(
        textwrap.dedent(
            """
            variables:
              SOPHIA_SECRET_KEY_CURRENT: hard-coded-production-secret-key
            """
        )
    )
    (proxy_dir / "Dockerfile").write_text(
        "ENV SOPHIA_SECRET_KEY_CURRENT=hard-coded-production-secret-key\n"
    )

    result = _run_policy(tmp_path)

    assert result.returncode == 1
    assert ".gitlab-ci.yml" in result.stderr
    assert "proxy/Dockerfile" in result.stderr
    assert "SOPHIA_SECRET_KEY_CURRENT" in result.stderr


def test_secret_policy_allows_placeholders_and_test_fixtures(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.prod.yml").write_text(
        textwrap.dedent(
            """
            services:
              api:
                environment:
                  SOPHIA_SECRET_KEY_CURRENT: ${SOPHIA_SECRET_KEY_CURRENT:?set current signing key}
                  SOPHIA_SECRET_KEY_PREVIOUS: ${SOPHIA_SECRET_KEY_PREVIOUS:-}
            """
        )
    )
    test_dir = tmp_path / "src" / "sophia" / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_fixture.py").write_text('storage_secret="explicit-safe-test-fixture"\n')

    result = _run_policy(tmp_path)

    assert result.returncode == 0, result.stderr


def test_secret_policy_cli_reports_violations(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "sophia"
    source_dir.mkdir(parents=True)
    (source_dir / "config.py").write_text('SECRET_KEY = "hard-coded-production-secret-key"\n')

    result = _run_policy(tmp_path)

    assert result.returncode == 1
    assert "src/sophia/config.py:1" in result.stderr
    assert "SECRET_KEY" in result.stderr


def _run_policy(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(POLICY_SCRIPT), "--root", str(root), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
