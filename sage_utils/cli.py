"""Argparse plumbing shared by the SAGE command-line entry points: path-validating argument
types, the UTF-8 stdout switch, and the `install-skill` subcommand every skill-shipping
package offers. Qt-free.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from sage_utils.skill import default_skills_dir

__all__ = [
    "add_game_arguments",
    "add_install_skill_parser",
    "existing_dir",
    "existing_file",
    "run_install_skill",
    "utf8_stdout",
]


def existing_dir(value: str) -> Path:
    """Argparse `type=` for an argument that must name an existing directory."""
    path = Path(value)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"not a directory: {value}")
    return path


def existing_file(value: str) -> Path:
    """Argparse `type=` for an argument that must name an existing file."""
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"not a file: {value}")
    return path


def utf8_stdout() -> None:
    """Re-open stdout as UTF-8, best effort. Game data carries non-ASCII display names
    (Lothlórien, Éomer); emit them as UTF-8 rather than letting a Windows console's default
    code page mangle them when a program or agent captures the output."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


def add_game_arguments(
    parser: argparse.ArgumentParser,
    *,
    game_required: bool = True,
    game_help: str,
) -> None:
    """Add the shared game-source pair (`--game` / `--cache`) that every CLI loading a game from
    user input offers. `--game` is repeatable and each value is an ini tree or a live install
    (`.big` archives are mounted); resolve them with `sage_utils.gameroot.resolve_game_roots`,
    which yields an ascending-priority list a later `--game` shadows an earlier one, file by
    file - pass a base game first and the mod after it to layer them. The `--game` wording
    differs per command, so pass it in; `--cache` is identical everywhere."""
    repeatable = (
        ". Repeatable; a later --game shadows an earlier one file by file (base game first,"
        " mod after it)."
    )
    parser.add_argument(
        "--game",
        type=Path,
        action="append",
        required=game_required,
        default=None,
        metavar="ROOT",
        help=game_help + repeatable,
    )
    parser.add_argument(
        "--cache", type=Path, default=None, help="where to mount an install's .big archives"
    )


def add_install_skill_parser(subparsers, skill_name: str) -> argparse.ArgumentParser:
    """Add the standard `install-skill` subcommand for `skill_name` to `subparsers`."""
    install = subparsers.add_parser("install-skill", help=f"install the bundled {skill_name} skill")
    install.add_argument(
        "--dest",
        type=Path,
        default=None,
        help=f"skills directory to install into (default: {default_skills_dir()})",
    )
    install.add_argument("--force", action="store_true", help="overwrite an existing install")
    return install


def run_install_skill(install: Callable[..., Path], dest: Path | None, force: bool) -> int:
    """Run a package's `install_skill` with the parsed `install-skill` arguments, reporting
    the outcome the way every SAGE CLI does."""
    try:
        installed = install(dest, force=force)
    except FileExistsError as exc:
        print(f"{exc} already exists; pass --force to overwrite")
        return 1
    print(f"installed skill to {installed}")
    return 0
