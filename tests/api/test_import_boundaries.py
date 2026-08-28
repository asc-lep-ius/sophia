"""Import-boundary checks for the backend API package."""

from __future__ import annotations

import ast
from pathlib import Path

API_ROOT = Path(__file__).parents[2] / "src" / "sophia" / "api"


def test_api_package_does_not_import_gui() -> None:
    assert API_ROOT.exists()

    gui_imports: list[str] = []
    for source_path in API_ROOT.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sophia.gui" or alias.name.startswith("sophia.gui."):
                        gui_imports.append(f"{source_path.relative_to(API_ROOT)}:{alias.name}")
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "sophia.gui" or module.startswith("sophia.gui."):
                    gui_imports.append(f"{source_path.relative_to(API_ROOT)}:{module}")

    assert gui_imports == []
