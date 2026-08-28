"""Build the repo's PyInstaller specs and zip the binaries into pySAGE.zip.

Discovers the `*.spec` files that live next to each package (sage_ini/sage-ini.spec, ...),
runs PyInstaller on each into a clean staging dir - not the repo's `dist/`, which holds stale
artifacts from ad-hoc builds - and zips whatever the specs emitted into `pySAGE.zip` at the
repo root. It also assembles the self-contained SageLint Sublime package (the loose folder
Sublime installs, carrying the freshly built sage_lint CLI in its bin/) into the same zip.

The mod overlays under `sage_mods` are left out of a plain run and built only when a filter
names them: a release of the engine-generic tools is for everyone, while the Edain windows are
for one mod's team, and shipping them to everybody costs build minutes and zip weight for an
app most people cannot use.

    python tools/build_release.py            # every generic spec, write pySAGE.zip
    python tools/build_release.py sage_ini   # only specs whose path contains "sage_ini"
    python tools/build_release.py edain      # the mod overlays, which a plain run skips

Each spec is a onefile build, so the staging dir ends up holding one binary per EXE the specs
declare (a few specs declare two: a console CLI and a windowed app). Every console binary is
built with `icon.ico` beside this script - one icon, so the release reads as one toolkit rather
than a folder of unrelated exes; the windowed apps each carry their own, next to the window they
title. PyInstaller binaries are not cross-platform, so the zip carries whatever this OS produced;
build once per OS you ship.
"""

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Staged apart from the repo's dist/ so stale hand-built exes never leak into the zip.
STAGE_DIR = REPO_ROOT / "build" / "release-dist"
WORK_DIR = REPO_ROOT / "build" / "release-work"
ZIP_PATH = REPO_ROOT / "pySAGE.zip"

# Trees whose specs a plain run leaves alone, matched against the repo-relative path. `sage_mods`
# holds the mod overlays: their windows name one mod's data and are wanted by that mod's team, not
# by everyone who downloads the release, so they are opt-in by filter.
OPTIONAL_DIRS = ("sage_mods/",)

# The Sublime plugin ships as a loose folder that carries a standalone sage_lint binary in bin/:
# it execs that binary via subprocess, and files inside a .sublime-package zip are never
# extracted to disk, so a zip install would leave nothing to run. sage-lint.spec already emits
# that CLI binary, so the release reuses it rather than freezing it a second time.
SUBLIME_SRC = REPO_ROOT / "sage_lint" / "plugins" / "sublime"
# Dev-only names kept out of the installable package (directory names match too).
SUBLIME_EXCLUDE = (
    "__pycache__",
    "bin",
    "build_package.bat",
    "install.sh",
    "install.bat",
    "generate_syntax.py",
)
# The CLI binary sage-lint.spec emits; the plugin looks for exactly this name in bin/.
CLI_BINARY_NAME = "sage_lint.exe" if sys.platform == "win32" else "sage_lint"


def find_specs(filters: list[str]) -> list[Path]:
    """The specs to build: every one in the repo, or - with `filters` - those whose repo-relative
    path contains one of them. The mod overlays are skipped unless a filter reaches them, so
    `edain` (or the spec's own name) is how they get built."""
    specs = sorted(REPO_ROOT.glob("*/**/*.spec"))
    paths = [(spec, spec.relative_to(REPO_ROOT).as_posix()) for spec in specs]
    if filters:
        return [spec for spec, path in paths if any(f in path for f in filters)]
    return [spec for spec, path in paths if not path.startswith(OPTIONAL_DIRS)]


def build(spec: Path) -> None:
    rel = spec.relative_to(REPO_ROOT)
    print(f"==> pyinstaller {rel}")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(STAGE_DIR),
            "--workpath",
            str(WORK_DIR),
            str(spec),
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def stage_sublime_package() -> bool:
    """Assemble the self-contained SageLint Sublime package folder inside the stage.

    Reuses the CLI binary sage-lint.spec already emitted into the stage rather than freezing it
    again. Returns False (with a note) when that binary is absent - e.g. a filtered build that
    left sage-lint.spec out - so the release simply ships without the plugin instead of failing.
    """
    binary = STAGE_DIR / CLI_BINARY_NAME
    if not binary.is_file():
        print(f"==> skipping Sublime package: no {CLI_BINARY_NAME} in stage (sage-lint unbuilt)")
        return False

    dest = STAGE_DIR / "SageLint"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(SUBLIME_SRC, dest, ignore=shutil.ignore_patterns(*SUBLIME_EXCLUDE))
    bin_dir = dest / "bin"
    bin_dir.mkdir(exist_ok=True)
    shutil.copy2(binary, bin_dir / CLI_BINARY_NAME)
    print(f"==> staged Sublime package  SageLint/ (bin/{CLI_BINARY_NAME})")
    return True


def make_zip() -> list[Path]:
    artifacts = sorted(p for p in STAGE_DIR.rglob("*") if p.is_file())
    if not artifacts:
        raise SystemExit("no artifacts were produced - nothing to zip")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in artifacts:
            zf.write(path, path.relative_to(STAGE_DIR))
    return artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "filters",
        nargs="*",
        help=(
            "only build specs whose repo-relative path contains one of these substrings; "
            f"also the only way to build the specs under {', '.join(OPTIONAL_DIRS)}, which a "
            "plain run skips"
        ),
    )
    args = parser.parse_args()

    specs = find_specs(args.filters)
    if not specs:
        raise SystemExit(f"no matching .spec files (filters: {args.filters or 'none'})")

    # Start from an empty stage so the zip reflects exactly this run.
    shutil.rmtree(STAGE_DIR, ignore_errors=True)
    STAGE_DIR.mkdir(parents=True, exist_ok=True)

    for spec in specs:
        build(spec)

    stage_sublime_package()

    artifacts = make_zip()
    total = sum(p.stat().st_size for p in artifacts)
    print(
        f"\nzipped {len(artifacts)} artifact(s) into {ZIP_PATH.relative_to(REPO_ROOT)} "
        f"({total / 1_048_576:.1f} MiB uncompressed):"
    )
    for path in artifacts:
        print(f"  {path.relative_to(STAGE_DIR)}")


if __name__ == "__main__":
    main()
