"""Frontend CI image tag policy tests."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from scripts.frontend_ci_image import check_root, content_tag, declared_tag

REPO_ROOT = Path(__file__).parents[2]
POLICY_SCRIPT = REPO_ROOT / "scripts" / "frontend_ci_image.py"


def test_repository_tag_is_current() -> None:
    assert check_root(REPO_ROOT) is None


def test_cli_passes_repository() -> None:
    result = _run_policy(REPO_ROOT)

    assert result.returncode == 0, result.stderr


def test_tag_matches_the_shell_hash_the_rebuild_job_pushed() -> None:
    """The tag in the registry was produced by `sha256sum | cut -c1-16`."""
    concatenated = b"".join(
        (REPO_ROOT / name).read_bytes()
        for name in ("ci/Dockerfile.frontend", "frontend/pnpm-lock.yaml")
    )

    assert content_tag(REPO_ROOT) == hashlib.sha256(concatenated).hexdigest()[:16]


def test_stale_tag_names_the_value_to_paste(tmp_path: Path) -> None:
    root = _seed(tmp_path, tag="0000000000000000")

    failure = check_root(root)

    assert failure is not None
    assert content_tag(root) in failure
    assert "rebuild-frontend-ci-image" in failure


def test_changing_an_input_moves_the_tag(tmp_path: Path) -> None:
    root = _seed(tmp_path, tag="0000000000000000")
    before = content_tag(root)
    (root / "frontend/pnpm-lock.yaml").write_text("playwright: 1.61.0\n")

    assert content_tag(root) != before


def test_missing_declaration_is_reported(tmp_path: Path) -> None:
    root = _seed(tmp_path, tag=None)

    failure = check_root(root)

    assert failure is not None
    assert "declares no FRONTEND_CI_TAG" in failure


def test_missing_input_is_reported(tmp_path: Path) -> None:
    root = _seed(tmp_path, tag="0000000000000000")
    (root / "ci/Dockerfile.frontend").unlink()

    failure = check_root(root)

    assert failure is not None
    assert "image inputs are missing" in failure


def test_declared_tag_reads_the_quoted_value() -> None:
    assert declared_tag('variables:\n  FRONTEND_CI_TAG: "abc123"\n') == "abc123"
    assert declared_tag("variables:\n  LOCAL_REGISTRY: nope\n") is None


def _seed(tmp_path: Path, *, tag: str | None) -> Path:
    (tmp_path / "ci").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "ci/Dockerfile.frontend").write_text("FROM node:24-bookworm-slim\n")
    (tmp_path / "frontend/pnpm-lock.yaml").write_text("playwright: 1.60.0\n")
    declaration = f'  FRONTEND_CI_TAG: "{tag}"\n' if tag is not None else ""
    (tmp_path / ".gitlab-ci.yml").write_text(f"variables:\n{declaration}")
    return tmp_path


def _run_policy(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(POLICY_SCRIPT), "--root", str(root), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
