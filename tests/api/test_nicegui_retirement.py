"""NiceGUI is gone, and every way it could come back partway is checked here.

Issue #102 retired the legacy web surface. The failure this module exists to
prevent is not a dramatic one: it is a half-retirement, where the import scan
comes back clean but a Dockerfile still builds the image, or CI still pushes
it, or the dependency is still resolved into every lock the pipeline installs
from. Each of those was a separate checklist item on the issue, so each is a
separate assertion here.

The source scans are parsed rather than grepped. ``services/course_overview.py``
says in its docstring where it was promoted from, and that provenance is worth
keeping — a scan that could not tell a sentence about NiceGUI from a call into
it would force the note out of the tree along with the code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"

DECISION_RECORDS = frozenset(
    {
        REPO_ROOT / "docs" / "nicegui-retirement.md",
        REPO_ROOT / "docs" / "frontend-long-tail-migration.md",
    }
)
"""The dated records of what was decided, exempt from the prose scan below.

Naming the thing it removed is what a decision record is *for* — #101's note
explains which guardrail each deleted module used to be, and this issue's own
record quotes the retired command in full. Exempting them by identity keeps the
scan binding on every document that tells a reader what to do, which is the
only kind that can send someone at a file that is not there.
"""

RETIRED_PACKAGES = ("nicegui", "sophia.gui")
RETIRED_SOURCE_PATHS = (
    "src/sophia/gui",
    "src/sophia/cli/gui.py",
    "tests/unit/gui",
    "tests/integration/gui",
    "Dockerfile.gui",
    "Dockerfile.gui.cuda",
    "Dockerfile.nicegui",
    "ci/Dockerfile.cuda-base",
)
RETIRED_IN_PROSE = (
    "sophia gui",
    "SOPHIA_GUI_",
    "SOPHIA_AUTO_SYNC",
    "make docker-gui",
    "make test-gui",
    "sophia-gui",
    *RETIRED_SOURCE_PATHS,
)
"""What a reader must not be told to run, type, set — or build.

The env vars matter as much as the command: ``Settings`` uses
``extra="ignore"``, so a stale ``SOPHIA_GUI_PORT`` copied out of an example
file is accepted in silence and does nothing, which is worse than being
rejected.

The deleted paths are here because checking them on disk is not the same as
checking them in prose, and the difference cost a round of review: the README
went on pointing at `ci/Dockerfile.cuda-base` for GPU transcription after the
file was deleted, and every path assertion below stayed green because the file
was, indeed, absent. Matching is case-insensitive so that "Sophia GUI" in a
sentence trips it too.
"""


def _source_modules() -> list[tuple[str, ast.Module]]:
    return [
        (path.relative_to(REPO_ROOT).as_posix(), ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(SRC_ROOT.rglob("*.py"))
    ]


def _imported_modules(tree: ast.Module) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module)
    return imported


def _attribute_roots(tree: ast.Module) -> set[str]:
    """Every ``name.attr`` pair reached through a bare name, as dotted strings."""
    return {
        f"{node.value.id}.{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    }


def test_no_module_under_src_imports_nicegui_or_the_gui_package() -> None:
    """The import half of the acceptance criterion, over all of ``src``.

    Broader than the API-package boundary this replaces: after the retirement
    there is no layer that may import ``sophia.gui``, so scoping the rule to
    one package would let a service or CLI module reintroduce it.
    """
    offenders = [
        f"{module}: {imported}"
        for module, tree in _source_modules()
        for imported in sorted(_imported_modules(tree))
        if any(imported == pkg or imported.startswith(f"{pkg}.") for pkg in RETIRED_PACKAGES)
    ]

    assert offenders == []


def test_no_nicegui_idiom_survives_in_source_code() -> None:
    """``app.storage`` and ``ui.<anything>`` — the two the issue names by hand.

    Both are how NiceGUI code reads rather than how it imports, so a module
    that rebound ``ui`` from a local alias would pass the import scan and fail
    here. Only a bare name is reached, not ``shim.ui.label()``; the import scan
    above is the real gate, and this is the second line of it.
    """
    offenders = [
        f"{module}: {reference}"
        for module, tree in _source_modules()
        for reference in sorted(_attribute_roots(tree))
        if reference.startswith("ui.") or reference == "app.storage"
    ]

    assert offenders == []


@pytest.mark.parametrize("retired_path", RETIRED_SOURCE_PATHS)
def test_the_retired_trees_and_images_are_gone(retired_path: str) -> None:
    assert not (REPO_ROOT / retired_path).exists()


def test_nicegui_is_not_a_declared_or_locked_dependency() -> None:
    """A clean import scan is not enough while the lock still resolves it.

    The CI image installs from ``uv.lock``, so a dependency left declared is a
    dependency shipped, scanned and patched for a surface that no longer runs.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")

    assert "nicegui" not in pyproject
    assert '\nname = "nicegui"\n' not in lock


def test_no_container_builds_or_runs_the_legacy_surface() -> None:
    development = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    production = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    for compose in (development, production):
        assert "sophia-gui" not in compose
        assert "nicegui" not in compose
        # The Hugging Face cache was mounted only by the GUI services; leaving
        # the volume declared would keep a stale model cache alive on the host.
        assert "model-cache" not in compose


def test_ci_neither_builds_nor_deploys_a_nicegui_image() -> None:
    ci = (REPO_ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")

    assert "nicegui" not in ci
    assert "Dockerfile.gui" not in ci


def _prose_files() -> list[Path]:
    """The documents that tell a reader what to do, minus the decision records.

    Excluding two files by identity rather than narrowing the glob: the scan is
    meant to bind on README, DEPLOYMENT and `.env.example`, which is where a
    dangling instruction actually costs someone an afternoon.
    """
    candidates = [*REPO_ROOT.glob("*.md"), *REPO_ROOT.glob("docs/*.md"), REPO_ROOT / ".env.example"]
    return [path for path in sorted(candidates) if path.is_file() and path not in DECISION_RECORDS]


@pytest.mark.parametrize("retired_reference", RETIRED_IN_PROSE)
def test_no_document_still_offers_something_this_issue_deleted(retired_reference: str) -> None:
    """Docs outlive code, and `.env.example` outlives both.

    A README that still offers `sophia gui launch` is a bug report waiting to
    be filed against a command that does not exist. Two rounds of review found
    one of these each: `.env.example` advertised `SOPHIA_GUI_PORT`, which
    `Settings` silently ignores, and a Make target deleted on the same branch;
    then the README went on naming `ci/Dockerfile.cuda-base` as the way to run
    GPU transcription after that file was deleted. Hence both the widened file
    set and the deleted paths in `RETIRED_IN_PROSE`.
    """
    needle = retired_reference.casefold()
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _prose_files()
        if needle in path.read_text(encoding="utf-8").casefold()
    ]

    assert offenders == []
