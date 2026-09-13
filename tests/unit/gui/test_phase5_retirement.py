"""The marking that tells phase 5 what it may delete.

Issue #99 step 6 asks for the legacy tests to be marked for removal, but only
once their replacements are green. A comment alone rots: it can name a file
that was renamed, or survive a replacement that was deleted, and either way the
phase 5 run finds out by deleting coverage nobody had. This turns the marking
into something that fails.
"""

from __future__ import annotations

import re
from pathlib import Path

MARKER = re.compile(r"^Phase 5 removal: superseded by (\S+?)\.$", re.MULTILINE)

REPO_ROOT = Path(__file__).resolve().parents[3]

EXPECTED_MARKED_MODULES = {
    "tests/integration/gui/test_dashboard.py",
    "tests/integration/gui/test_review_flow.py",
    "tests/unit/gui/test_dashboard.py",
    "tests/unit/gui/test_quickstart.py",
    "tests/unit/gui/test_review.py",
    "tests/unit/gui/test_review_card.py",
}


def _marked_modules() -> dict[str, list[str]]:
    marked: dict[str, list[str]] = {}
    for path in sorted((REPO_ROOT / "tests").rglob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        replacements = MARKER.findall(path.read_text(encoding="utf-8"))
        if replacements:
            marked[path.relative_to(REPO_ROOT).as_posix()] = replacements
    return marked


def test_exactly_the_migrated_page_tests_are_marked() -> None:
    assert set(_marked_modules()) == EXPECTED_MARKED_MODULES


def test_every_marked_module_names_a_replacement_that_exists() -> None:
    """A marked module is only safe to delete while its replacement is there.

    Deleting or renaming the SvelteKit test without unmarking the NiceGUI one
    fails here rather than in the phase 5 run that quietly drops both.
    """
    for module, replacements in _marked_modules().items():
        for replacement in replacements:
            assert (REPO_ROOT / replacement).is_file(), f"{module} -> {replacement}"
