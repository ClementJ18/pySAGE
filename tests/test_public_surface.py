"""CONVENTIONS rule 1: a module another shipped package imports names from declares `__all__`, as
does every package `__init__` that exports anything, and every name an `__all__` lists exists."""

import ast
import importlib
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _shipped_packages() -> set[str]:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        name.rstrip("*") for name in config["tool"]["setuptools"]["packages"]["find"]["include"]
    }


def _module_name(path: str) -> str:
    parts = PurePosixPath(path).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _tree(path: str) -> ast.Module:
    return ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))


def _declares_all(tree: ast.Module) -> bool:
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in targets
        ):
            return True
    return False


def _modules_needing_all() -> dict[str, str]:
    packages = _shipped_packages()
    listed = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    files = [f for f in listed if f.split("/")[0] in packages and (REPO_ROOT / f).exists()]
    modules = {_module_name(f): f for f in files}
    needing: dict[str, str] = {}
    for path in files:
        importer = path.split("/")[0]
        for node in ast.walk(_tree(path)):
            if not (isinstance(node, ast.ImportFrom) and node.module and node.level == 0):
                continue
            target = node.module
            if target not in modules or target.split(".")[0] == importer:
                continue
            # `from pkg import submodule` imports a module, not a name `pkg` exports.
            if all(f"{target}.{alias.name}" in modules for alias in node.names):
                continue
            needing[target] = modules[target]
    for name, path in modules.items():
        if path.endswith("__init__.py") and any(
            not isinstance(node, ast.Expr) for node in _tree(path).body
        ):
            needing[name] = path
    return {name: path for name, path in needing.items() if not name.endswith("__main__")}


NEEDING_ALL = _modules_needing_all()


def test_the_rule_covers_something():
    assert len(NEEDING_ALL) > 50


@pytest.mark.parametrize("module", sorted(NEEDING_ALL))
def test_module_declares_all(module: str):
    assert _declares_all(_tree(NEEDING_ALL[module])), (
        f"{module} is imported from another package (or is a package __init__) but has no "
        f"__all__; list its public names (CONVENTIONS rule 1)"
    )


@pytest.mark.parametrize("module", sorted(NEEDING_ALL))
def test_all_names_resolve(module: str):
    try:
        imported = importlib.import_module(module)
    except ImportError as exc:  # an optional extra (Qt, pyBIG, ...) that is not installed
        pytest.skip(str(exc))
    missing = [name for name in getattr(imported, "__all__", ()) if not hasattr(imported, name)]
    assert not missing, f"{module}.__all__ lists names it does not define: {missing}"
