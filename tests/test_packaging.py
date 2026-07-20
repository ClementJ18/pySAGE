"""Guards that every runtime asset is declared in `[tool.setuptools.package-data]`.

An undeclared data file is not a build error - it is absent from the wheel, and since the loaders
degrade quietly (a missing texture returns None, a missing icon leaves the default) the omission
surfaces as a feature silently not working. This test expands the declared globs against the
source tree and asserts they cover every runtime asset.

Runs from the source checkout with no build step, so it is core-suite and platform-independent.
"""

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files a package opens at runtime, by extension, plus the PEP 561 marker. Documentation that
# merely lives inside a package directory (PLAN.md, TODO.md, order_space_map.md) is deliberately
# absent: it is not loaded, so it need not ship.
ASSET_SUFFIXES = frozenset({".png", ".ico", ".webp", ".html", ".css", ".js", ".tga", ".dds"})
ASSET_NAMES = frozenset({"py.typed"})

# The Sublime Text plugin is installed by copying the folder into Sublime's Packages directory
# (see its install.sh / install.bat), not by pip, so it is intentionally not package data.
EXCLUDED_DIRS = ("sage_lint/plugins/sublime",)


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _declared_files() -> set[Path]:
    """Every path the declared package-data globs actually match in the source tree.

    Expanded with `Path.glob` rather than pattern-matched by hand so the result is exactly what
    setuptools will resolve, `**` and all."""
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]
    matched: set[Path] = set()
    for package, patterns in package_data.items():
        package_dir = REPO_ROOT / package.replace(".", "/")
        for pattern in patterns:
            matched.update(path.resolve() for path in package_dir.glob(pattern) if path.is_file())
    return matched


def _shipped_packages() -> list[Path]:
    includes = _pyproject()["tool"]["setuptools"]["packages"]["find"]["include"]
    return [REPO_ROOT / name.removesuffix("*") for name in includes]


def _runtime_assets() -> list[Path]:
    assets: list[Path] = []
    for package_dir in _shipped_packages():
        for path in package_dir.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            if any(relative.startswith(excluded) for excluded in EXCLUDED_DIRS):
                continue
            if path.suffix.lower() in ASSET_SUFFIXES or path.name in ASSET_NAMES:
                assets.append(path.resolve())
    return sorted(assets)


def test_the_tree_actually_contains_assets_to_check():
    """Guards the guard: a bad glob or a moved package must not make this file vacuously pass."""
    assert len(_runtime_assets()) > 20


@pytest.mark.parametrize(
    "asset", _runtime_assets(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix()
)
def test_runtime_asset_is_declared_as_package_data(asset: Path):
    declared = _declared_files()
    relative = asset.relative_to(REPO_ROOT).as_posix()
    assert asset in declared, (
        f"{relative} is loaded at runtime but no [tool.setuptools.package-data] glob matches it, "
        f"so it will be missing from the wheel (and silently unavailable to pip users). Add a "
        f"pattern for it, or exclude it in this test if it genuinely does not need to ship."
    )
