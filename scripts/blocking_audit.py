"""Audit async API routers for unwrapped blocking I/O calls."""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROUTERS_DIR = Path("src/sophia/api/routers")
RUN_SYNC_CALL = "anyio.to_thread.run_sync"
BLOCKING_EXACT_CALLS = {
    "open",
    "os.system",
    "requests.delete",
    "requests.get",
    "requests.patch",
    "requests.post",
    "requests.put",
    "shutil.copy",
    "shutil.copy2",
    "shutil.copyfile",
    "shutil.move",
    "shutil.rmtree",
    "sqlite3.connect",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "subprocess.run",
    "time.sleep",
}
BLOCKING_METHODS = {
    "glob",
    "iterdir",
    "mkdir",
    "open",
    "read_bytes",
    "read_text",
    "rename",
    "replace",
    "rglob",
    "rmdir",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}
SERVICE_BOUNDARY_TOKENS = ("adapter", "service")


@dataclass(frozen=True, slots=True)
class Violation:
    path: Path
    line: int
    function_name: str
    call_name: str
    reason: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to audit. Defaults to the current directory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return a non-zero exit status when violations are found.",
    )
    args = parser.parse_args(argv)

    violations = audit_root(args.root)
    if violations:
        _write_violations(args.root, violations)
        return 1
    return 0


def audit_root(root: Path) -> list[Violation]:
    routers_dir = root / ROUTERS_DIR
    if not routers_dir.exists():
        return []

    violations: list[Violation] = []
    for router_file in sorted(routers_dir.glob("*.py")):
        if router_file.name == "__init__.py":
            continue
        violations.extend(audit_file(router_file))
    return sorted(violations, key=lambda violation: (violation.path, violation.line))


def audit_file(path: Path) -> list[Violation]:
    tree = ast.parse(path.read_text(), filename=str(path))
    import_aliases = _import_aliases(tree)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            visitor = _BlockingCallVisitor(path, node.name, import_aliases)
            visitor.visit_statements(node.body)
            violations.extend(visitor.violations)
    return violations


class _BlockingCallVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, function_name: str, import_aliases: dict[str, str]) -> None:
        self.path = path
        self.function_name = function_name
        self.import_aliases = import_aliases
        self.await_depth = 0
        self.violations: list[Violation] = []

    def visit_statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self.visit(statement)

    def visit_Await(self, node: ast.Await) -> None:  # noqa: N802
        self.await_depth += 1
        self.visit(node.value)
        self.await_depth -= 1

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        self._visit_lambda_defaults(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        call_name = _normalized_call_name(node.func, self.import_aliases)
        if call_name == RUN_SYNC_CALL:
            self._visit_run_sync_arguments(node)
            return

        if call_name is not None:
            reason = _blocking_reason(call_name)
            if reason is not None:
                self.violations.append(
                    Violation(self.path, node.lineno, self.function_name, call_name, reason)
                )
            elif self.await_depth == 0 and _is_service_boundary(call_name):
                self.violations.append(
                    Violation(
                        self.path,
                        node.lineno,
                        self.function_name,
                        call_name,
                        "service/adapter boundary must be async or thread-wrapped",
                    )
                )

        self._visit_call_children(node)

    def _visit_run_sync_arguments(self, node: ast.Call) -> None:
        if node.args:
            self._visit_run_sync_callable(node.args[0])
            for argument in node.args[1:]:
                self._visit_eager_expression(argument)

        for keyword in node.keywords:
            if keyword.arg == "func":
                self._visit_run_sync_callable(keyword.value)
            else:
                self._visit_eager_expression(keyword.value)

    def _visit_run_sync_callable(self, node: ast.AST) -> None:
        if isinstance(node, ast.Call):
            self._visit_eager_expression(node)
            return

        self._visit_callable_reference(node)

    def _visit_callable_reference(self, node: ast.AST) -> None:
        self.visit(node)

    def _visit_eager_expression(self, node: ast.AST) -> None:
        self.visit(node)

    def _visit_call_children(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Lambda):
            self._visit_lambda_defaults(node.func)
            for argument in node.args:
                self._visit_eager_expression(argument)
            for keyword in node.keywords:
                self._visit_eager_expression(keyword.value)
            self.visit(node.func.body)
            return

        self.visit(node.func)
        for argument in node.args:
            self._visit_eager_expression(argument)
        for keyword in node.keywords:
            self._visit_eager_expression(keyword.value)

    def _visit_lambda_defaults(self, node: ast.Lambda) -> None:
        for default in node.args.defaults:
            self._visit_eager_expression(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self._visit_eager_expression(default)


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    blocking_modules = {
        call_name.split(".", maxsplit=1)[0]
        for call_name in BLOCKING_EXACT_CALLS
        if "." in call_name
    }
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_root = alias.name.split(".", maxsplit=1)[0]
                if module_root in blocking_modules:
                    bound_name = alias.asname or module_root
                    canonical_name = alias.name if alias.asname else module_root
                    aliases[bound_name] = canonical_name
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or node.level != 0:
                continue
            for alias in node.names:
                imported_name = f"{node.module}.{alias.name}"
                if imported_name in BLOCKING_EXACT_CALLS:
                    aliases[alias.asname or alias.name] = imported_name
    return aliases


def _normalized_call_name(node: ast.AST, import_aliases: dict[str, str]) -> str | None:
    call_name = _call_name(node)
    if call_name is None:
        return None

    root, separator, remainder = call_name.partition(".")
    if root not in import_aliases:
        return call_name
    return f"{import_aliases[root]}{separator}{remainder}"


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent_name = _call_name(node.value)
        if parent_name is None:
            return node.attr
        return f"{parent_name}.{node.attr}"
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return None


def _blocking_reason(call_name: str) -> str | None:
    if call_name in BLOCKING_EXACT_CALLS:
        return "blocking standard-library or requests call"

    method_name = call_name.rsplit(".", maxsplit=1)[-1]
    if method_name in BLOCKING_METHODS:
        return "blocking filesystem call"
    return None


def _is_service_boundary(call_name: str) -> bool:
    lowered = call_name.lower()
    return any(token in lowered for token in SERVICE_BOUNDARY_TOKENS)


def _write_violations(root: Path, violations: list[Violation]) -> None:
    sys.stderr.write(
        "Blocking I/O violations found. Wrap sync I/O in "
        f"{RUN_SYNC_CALL} or move the work behind an async boundary.\n"
    )
    for violation in violations:
        relative_path = _relative_path(root, violation.path)
        sys.stderr.write(
            f"{relative_path}:{violation.line} in {violation.function_name}: "
            f"{violation.call_name} ({violation.reason})\n"
        )


def _relative_path(root: Path, path: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


if __name__ == "__main__":
    raise SystemExit(main())
