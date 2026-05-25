"""Reject hard-coded production-like secret literals."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SOURCE_DIR = Path("src")
DOCKERFILE_DIRS = (Path("."), Path("ci"))
COMPOSE_FILE_NAMES = (
    "docker-compose.yml",
    "docker-compose.prod.yml",
)
SECRET_NAME_PATTERN = re.compile(r"(?:SECRET_KEY|STORAGE_SECRET)", re.IGNORECASE)
DOCKER_SECRET_PATTERN = re.compile(
    r"^\s*(?:ENV|ARG)\s+"
    r"(?P<name>[A-Z0-9_]*(?:SECRET_KEY|STORAGE_SECRET)[A-Z0-9_]*)"
    r"(?:\s*=\s*|\s+)(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
COMPOSE_MAPPING_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Z0-9_]*(?:SECRET_KEY|STORAGE_SECRET)[A-Z0-9_]*):"
    r"\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
COMPOSE_LIST_PATTERN = re.compile(
    r"^\s*-\s*(?P<name>[A-Z0-9_]*(?:SECRET_KEY|STORAGE_SECRET)[A-Z0-9_]*)"
    r"=(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
ENV_PLACEHOLDER_PATTERN = re.compile(
    r"^\$\{[A-Z0-9_]+(?:(?P<operator>:-|-|:\?|\?)(?P<body>[^}]*))?\}$"
)
SHELL_ENV_PATTERN = re.compile(r"^\$[A-Z0-9_]+$")
EXPLICIT_SAFE_LITERAL_VALUES = frozenset(
    {
        "dummy",
        "local-development",
        "not-a-secret",
        "placeholder",
        "sophia-local-development-secret-key",
    }
)
TEST_PATH_PARTS = frozenset({"test", "tests", "fixtures"})
TEST_ONLY_LITERAL_MARKERS = (
    "example",
    "fixture",
    "test",
)


@dataclass(frozen=True, slots=True)
class SecretPolicyViolation:
    """A hard-coded secret-like literal found by the policy scanner."""

    path: Path
    line: int
    name: str
    value: str
    reason: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return a non-zero exit status when violations are found.",
    )
    args = parser.parse_args(argv)

    violations = scan_root(args.root)
    if violations:
        _write_violations(violations)
        return 1
    return 0


def scan_root(root: Path) -> list[SecretPolicyViolation]:
    """Scan a repository root for hard-coded production-like secrets."""
    resolved_root = root.resolve()
    violations: list[SecretPolicyViolation] = []

    for python_file in _python_source_files(resolved_root):
        violations.extend(_scan_python_file(resolved_root, python_file))

    for policy_file in _policy_files(resolved_root):
        violations.extend(_scan_text_policy_file(resolved_root, policy_file))

    return sorted(violations, key=lambda violation: (violation.path.as_posix(), violation.line))


def _python_source_files(root: Path) -> list[Path]:
    source_dir = root / SOURCE_DIR
    if not source_dir.exists():
        return []
    return sorted(path for path in source_dir.rglob("*.py") if path.is_file())


def _policy_files(root: Path) -> list[Path]:
    policy_files: set[Path] = set()
    for dockerfile_dir in DOCKERFILE_DIRS:
        policy_files.update((root / dockerfile_dir).glob("Dockerfile*"))
    policy_files.update(root / file_name for file_name in COMPOSE_FILE_NAMES)
    return sorted(path for path in policy_files if path.is_file())


def _scan_python_file(root: Path, path: Path) -> list[SecretPolicyViolation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _PythonSecretVisitor(root, path)
    visitor.visit(tree)
    return visitor.violations


class _PythonSecretVisitor(ast.NodeVisitor):
    def __init__(self, root: Path, path: Path) -> None:
        self.root = root
        self.path = path
        self.violations: list[SecretPolicyViolation] = []

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for target in node.targets:
            self._check_literal(_target_name(target), node.value, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if node.value is not None:
            self._check_literal(_target_name(node.target), node.value, node.lineno)
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        self._check_literal(node.arg, node.value, getattr(node.value, "lineno", 0))
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:  # noqa: N802
        for key_node, value_node in zip(node.keys, node.values, strict=True):
            self._check_literal(
                _string_literal(key_node),
                value_node,
                getattr(key_node, "lineno", node.lineno),
            )
        self.generic_visit(node)

    def _check_literal(self, name: str | None, value_node: ast.AST, line: int) -> None:
        if name is None or not _is_secret_name(name):
            return
        if not isinstance(value_node, ast.Constant) or not isinstance(value_node.value, str):
            return
        value = value_node.value
        relative_path = _relative_path(self.root, self.path)
        if _is_allowed_value(value, relative_path):
            return
        self.violations.append(
            SecretPolicyViolation(
                path=relative_path,
                line=line,
                name=name,
                value=value,
                reason="hard-coded secret-like Python literal",
            )
        )


def _scan_text_policy_file(root: Path, path: Path) -> list[SecretPolicyViolation]:
    violations: list[SecretPolicyViolation] = []
    relative_path = _relative_path(root, path)
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped_line = raw_line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        match = _text_secret_match(raw_line)
        if match is None:
            continue
        name = match.group("name")
        value = _clean_text_value(match.group("value"))
        if _is_allowed_value(value, relative_path):
            continue
        violations.append(
            SecretPolicyViolation(
                path=relative_path,
                line=line_number,
                name=name,
                value=value,
                reason="hard-coded secret-like Docker/Compose literal",
            )
        )
    return violations


def _text_secret_match(line: str) -> re.Match[str] | None:
    for pattern in (DOCKER_SECRET_PATTERN, COMPOSE_MAPPING_PATTERN, COMPOSE_LIST_PATTERN):
        match = pattern.match(line)
        if match is not None:
            return match
    return None


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _string_literal(node.slice)
    return None


def _string_literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_secret_name(name: str) -> bool:
    return SECRET_NAME_PATTERN.search(name) is not None


def _is_allowed_value(value: str, path: Path | None) -> bool:
    cleaned_value = _clean_text_value(value)
    if not cleaned_value:
        return True
    if _is_env_placeholder(cleaned_value):
        return True
    lowered_value = cleaned_value.lower()
    if lowered_value in EXPLICIT_SAFE_LITERAL_VALUES:
        return True
    if path is not None and _is_test_path(path):
        return any(marker in lowered_value for marker in TEST_ONLY_LITERAL_MARKERS)
    return False


def _is_test_path(path: Path) -> bool:
    return path.name.startswith("test_") or any(
        part.lower() in TEST_PATH_PARTS for part in path.parts
    )


def _is_env_placeholder(value: str) -> bool:
    if SHELL_ENV_PATTERN.fullmatch(value) is not None:
        return True

    match = ENV_PLACEHOLDER_PATTERN.fullmatch(value)
    if match is None:
        return False

    operator = match.group("operator")
    body = match.group("body") or ""
    if operator is None:
        return True
    if operator in {":?", "?"}:
        return True
    return body == ""


def _clean_text_value(value: str) -> str:
    cleaned_value = value.strip().rstrip(",")
    if (
        len(cleaned_value) >= 2
        and cleaned_value[0] == cleaned_value[-1]
        and cleaned_value.startswith(("'", '"'))
    ):
        return cleaned_value[1:-1]
    return cleaned_value


def _write_violations(violations: list[SecretPolicyViolation]) -> None:
    sys.stderr.write(
        "Secret policy violations found. Move production secrets to environment "
        "variables or explicit safe placeholders.\n"
    )
    for violation in violations:
        sys.stderr.write(
            f"{violation.path}:{violation.line}: {violation.name} ({violation.reason})\n"
        )


def _relative_path(root: Path, path: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


if __name__ == "__main__":
    raise SystemExit(main())
