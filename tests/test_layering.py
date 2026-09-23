"""Import layering between packages, so no import cycle can form.

`sage_utils` has a dependency-free base (streams, CLI plumbing, config, the file system) and a
game-data layer built on `sage_ini` (sources, views, the faction graph, the Qt widgets). The core
format packages may use only the base. Likewise the editor may not depend on the test framework.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Packages the dependency-free base of sage_utils must never reach, directly or transitively.
_GAME_PACKAGES = ("sage_ini", "sage_map", "sage_replay", "sage_save", "sage_live")


def _module_name(path: Path) -> str:
    parts = path.relative_to(REPO_ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return {name for name in found if name.startswith("sage_")}


def _package_imports(package: str) -> dict[str, set[str]]:
    return {_module_name(path): _imports(path) for path in (REPO_ROOT / package).rglob("*.py")}


UTILS = _package_imports("sage_utils")


def _reaches_game_package(module: str, seen: frozenset[str] = frozenset()) -> str | None:
    for dep in UTILS.get(module, ()):
        if dep.split(".")[0] in _GAME_PACKAGES:
            return dep
        if dep in UTILS and dep not in seen:
            found = _reaches_game_package(dep, seen | {module})
            if found:
                return found
    return None


@pytest.mark.parametrize("package", ["sage_ini", "sage_map"])
def test_core_packages_use_only_the_utils_base(package: str):
    offending = {
        f"{module} -> {dep} (reaches {reached})"
        for module, deps in _package_imports(package).items()
        for dep in deps
        if dep in UTILS and (reached := _reaches_game_package(dep))
    }
    assert not offending, f"{package} imports sage_utils' game-data layer: {sorted(offending)}"


def test_worldbuilder_does_not_depend_on_the_test_framework():
    offending = {
        f"{module} -> {dep}"
        for module, deps in _package_imports("sage_worldbuilder").items()
        for dep in deps
        if dep.split(".")[0] == "sage_test"
    }
    assert not offending, sorted(offending)
