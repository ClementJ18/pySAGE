"""Guards that every runtime asset is declared in `[tool.setuptools.package-data]`.

An undeclared data file is not a build error - it is absent from the wheel, and since the loaders
degrade quietly (a missing texture returns None, a missing icon leaves the default) the omission
surfaces as a feature silently not working. This test expands the declared globs against the
source tree and asserts they cover every runtime asset.

Runs from the source checkout with no build step, so it is core-suite and platform-independent.
"""

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Files a package opens at runtime, by extension, plus the PEP 561 marker. Documentation that
# merely lives inside a package directory (PLAN.md, TODO.md, order_space_map.md) is deliberately
# absent: it is not loaded, so it need not ship.
ASSET_SUFFIXES = frozenset({".png", ".ico", ".webp", ".html", ".css", ".js", ".tga", ".dds"})
ASSET_NAMES = frozenset({"py.typed"})

# The Sublime Text plugin is installed by copying the folder into Sublime's Packages directory
# (see its install.sh / install.bat), not by pip, so it is intentionally not package data.
EXCLUDED_DIRS = ("sage_lint/plugins/sublime",)

# Build-time-only assets: consumed by a PyInstaller spec, never opened by the running package, so
# they have no reason to sit in the wheel. An icon PyInstaller *embeds* in an exe (`icon=[ICON]`
# in a spec, with an empty `datas`) belongs here - unlike every icon a Qt window loads from disk
# at runtime, which must ship. Empty today: every asset under a shipped package is a runtime one.
EXCLUDED_FILES: tuple[str, ...] = ()


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
            if relative in EXCLUDED_FILES:
                continue
            if path.suffix.lower() in ASSET_SUFFIXES or path.name in ASSET_NAMES:
                assets.append(path.resolve())
    return sorted(assets)


def test_the_tree_actually_contains_assets_to_check():
    """Guards the guard: a bad glob or a moved package must not make this file vacuously pass.

    A floor well under the current count, not a target - a package leaving the repo (as the mod
    overlays did) legitimately lowers it, and only a collapse to near-nothing is a broken glob."""
    assert len(_runtime_assets()) > 12


def test_exemptions_still_point_at_something():
    """A renamed or deleted exemption must not linger: a stale entry silently excuses whatever
    later takes that path."""
    for relative in EXCLUDED_DIRS:
        assert (REPO_ROOT / relative).is_dir(), f"excluded directory {relative} no longer exists"
    for relative in EXCLUDED_FILES:
        assert (REPO_ROOT / relative).is_file(), f"excluded file {relative} no longer exists"


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


def test_all_extra_aggregates_every_other_extra():
    """The `all` extra must self-reference every other optional extra, so `pip install .[all]`
    (which CI's full job uses) can never silently miss one - the exact gap that once let a new
    extra ship without its Qt-backed suite ever running in CI. Runs in the core suite (it only
    parses pyproject.toml), so a forgotten extra fails fast everywhere, not just where the extras
    are installed."""
    project = _pyproject()["project"]
    name = project["name"]
    extras = project["optional-dependencies"]
    assert "all" in extras, "no aggregate `all` extra in [project.optional-dependencies]"

    referenced: set[str] = set()
    for entry in extras["all"]:
        assert entry.startswith(f"{name}[") and entry.endswith("]"), (
            f"`all` entry {entry!r} must be a self-reference of the form {name}[<extra>]"
        )
        referenced.add(entry[len(name) + 1 : -1])

    others = set(extras) - {"all"}
    assert referenced == others, (
        f"`all` must reference exactly the other extras - "
        f"missing {sorted(others - referenced)}, unknown {sorted(referenced - others)}"
    )


def _ci_checked_scripts() -> set[str]:
    """The entry-point names CI's `package` job actually runs, read out of its two `for script in
    ... ; do` loops. Scraped from the YAML as text rather than parsed: the core suite has no YAML
    reader, and the shell loop - not the surrounding structure - is what decides the coverage."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    loops = re.findall(r"for script in ([^;]+); do", text)
    assert loops, f"no `for script in ...; do` loop found in {CI_WORKFLOW.name}"
    return {name for loop in loops for name in loop.split()}


def test_ci_runs_every_declared_entry_point():
    """Every console and GUI script must be exercised by CI's `package` job - the CLIs with
    `--help`, the desktop apps by asserting they name their missing extra. The lists there are
    hand-written shell loops, so a newly added entry point is silently uncovered until something
    checks - a GUI script once shipped exactly that way, with four CLIs drifted out beside it.
    Parses only pyproject.toml and the workflow text, so it runs in the core suite."""
    project = _pyproject()["project"]
    declared = set(project["scripts"]) | set(project["gui-scripts"])
    checked = _ci_checked_scripts()

    assert declared <= checked, (
        f"entry point(s) {sorted(declared - checked)} are declared in pyproject.toml but never run "
        f"by CI's `package` job; add them to the matching `for script in ...` loop in "
        f"{CI_WORKFLOW.name} (console scripts to the `--help` loop, desktop apps to the "
        f"missing-extra loop)."
    )
    assert checked <= declared, (
        f"CI's `package` job runs {sorted(checked - declared)}, which pyproject.toml does not "
        f"declare as an entry point - a renamed or removed script leaves the job failing."
    )
