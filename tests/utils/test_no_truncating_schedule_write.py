import ast
from pathlib import Path

import pytest

EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "vendor",
}


def _production_python_files(project_root: Path):
    """Yield every non-test Python module in the repository."""
    for py_file in project_root.rglob("*.py"):
        relative_path = py_file.relative_to(project_root)
        if any(part in EXCLUDED_DIRS for part in relative_path.parts):
            continue
        if "tests" in relative_path.parts:
            continue
        if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
            continue
        yield py_file


def _find_truncating_schedule_writes() -> list[str]:
    project_root = Path(__file__).parents[2]
    violations: list[str] = []

    for py_file in _production_python_files(project_root):
        relative_path = py_file.relative_to(project_root)

        source_text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=str(relative_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "open" or len(node.args) < 1:
                continue
            mode = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "mode"),
                node.args[1] if len(node.args) > 1 else None,
            )
            if not isinstance(mode, ast.Constant) or mode.value != "w":
                continue
            source = ast.get_source_segment(source_text, node)
            if source and "schedule" in source.lower():
                violations.append(f"{relative_path}:{node.lineno}: {source}")

    return violations


def test_no_production_schedule_write_uses_truncating_open() -> None:
    violations = _find_truncating_schedule_writes()
    if violations:
        pytest.fail("Found truncating schedule writes:\n" + "\n".join(violations))
