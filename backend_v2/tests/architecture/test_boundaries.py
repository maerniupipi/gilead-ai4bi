"""Executable architecture rules for the first backend slice."""

from __future__ import annotations

import ast
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "xiaoying_quick"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_new_backend_never_imports_legacy_backend() -> None:
    violations: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        for imported in _imports(path):
            if imported == "backend" or imported.startswith("backend."):
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert violations == []


def test_domain_modules_do_not_import_frameworks_or_outer_layers() -> None:
    forbidden = (
        "fastapi",
        "sqlalchemy",
        "pymysql",
        "psycopg",
        "xiaoying_quick.api",
        "xiaoying_quick.application",
        "xiaoying_quick.bootstrap",
        "xiaoying_quick.infrastructure",
    )
    violations: list[str] = []
    for path in (PACKAGE / "modules").rglob("*.py"):
        for imported in _imports(path):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden):
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert violations == []


def test_domain_modules_use_other_modules_public_facades() -> None:
    violations: list[str] = []
    modules_root = PACKAGE / "modules"
    for path in modules_root.rglob("*.py"):
        owner = path.relative_to(modules_root).parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imports(path):
            prefix = "xiaoying_quick.modules."
            if not imported.startswith(prefix):
                continue
            parts = imported.split(".")
            if len(parts) > 3 and parts[2] != owner:
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level != 2 or not node.module:
                continue
            target = node.module.split(".")
            if len(target) > 1 and target[0] != owner:
                violations.append(f"{path.relative_to(ROOT)} -> relative:{node.module}")
    assert violations == []


def test_required_runtime_and_development_dependencies_are_declared() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = {
        item.split("[")[0].split(">=")[0].lower() for item in document["project"]["dependencies"]
    }
    development = {
        item.split("[")[0].split(">=")[0].lower()
        for item in document["project"]["optional-dependencies"]["dev"]
    }
    assert {"alembic", "sqlglot", "cryptography", "httpx", "pymysql", "psycopg"} <= runtime
    assert {"pytest", "ruff", "mypy"} <= development
