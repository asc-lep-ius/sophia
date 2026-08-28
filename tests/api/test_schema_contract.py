"""Static checks for stable API schema contracts."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from sophia.api import create_api_app

REPO_ROOT = Path(__file__).parents[2]
SCHEMAS_DIR = REPO_ROOT / "src" / "sophia" / "api" / "schemas"
UNSTABLE_SCHEMA_NAME = re.compile(r"(^Body_)|(__)")
HTTP_METHODS = {"delete", "get", "patch", "post", "put"}


def _schema_module_files(root: Path = SCHEMAS_DIR) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def test_schema_module_scan_includes_nested_packages(tmp_path: Path) -> None:
    nested_dir = tmp_path / "study"
    nested_dir.mkdir()
    top_level_schema = tmp_path / "common.py"
    nested_schema = nested_dir / "responses.py"
    top_level_schema.write_text("from pydantic import BaseModel\n")
    nested_schema.write_text("from pydantic import BaseModel\n")

    scanned_files = [path.relative_to(tmp_path) for path in _schema_module_files(tmp_path)]

    assert scanned_files == [Path("common.py"), Path("study/responses.py")]


def test_schema_modules_do_not_use_any_or_intenum() -> None:
    violations: list[str] = []
    for schema_file in _schema_module_files():
        tree = ast.parse(schema_file.read_text(), filename=str(schema_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in {"Any", "IntEnum"}:
                violations.append(f"{schema_file.relative_to(SCHEMAS_DIR)}:{node.lineno}:{node.id}")
            if isinstance(node, ast.Attribute) and node.attr in {"Any", "IntEnum"}:
                violations.append(
                    f"{schema_file.relative_to(SCHEMAS_DIR)}:{node.lineno}:{node.attr}"
                )

    assert violations == []


def test_openapi_schema_names_are_stable() -> None:
    openapi = create_api_app().openapi()
    schemas = openapi.get("components", {}).get("schemas", {})
    unstable_names = sorted(
        schema_name for schema_name in schemas if UNSTABLE_SCHEMA_NAME.search(schema_name)
    )

    assert unstable_names == []


def test_request_bodies_use_named_components() -> None:
    openapi = create_api_app().openapi()
    anonymous_request_bodies: list[str] = []
    paths = openapi.get("paths", {})
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            request_body = operation.get("requestBody")
            if not isinstance(request_body, dict):
                continue
            content = request_body.get("content")
            if not isinstance(content, dict):
                continue
            for media_type, media_schema in content.items():
                if not isinstance(media_schema, dict):
                    continue
                schema = media_schema.get("schema")
                if isinstance(schema, dict) and "$ref" not in schema:
                    anonymous_request_bodies.append(f"{method.upper()} {path} {media_type}")

    assert anonymous_request_bodies == []
