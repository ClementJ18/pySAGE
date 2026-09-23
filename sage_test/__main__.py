"""Command-line entry point: `python -m sage_test <command>` (or `sage-test`).

The part of `sage_test` that is useful by hand. Running a scenario or a mission test is Python -
it is assertions, not a command - but *getting a map in front of the engine* is a command, and
it is the step you want before there is a test at all.

- `install-map <folder>` - copy a map's folder into the game's user-files `Maps` directory, where
  the engine caches it itself. This is how a map its own mod does not list as multiplayer - a
  campaign mission, a War of the Ring map - becomes startable: from the skirmish map list by
  hand, or with `-file` from `sage_test.run`. `--extras` brings along the sibling folders the
  map's `map.ini` reaches for with a relative `#include`, without which the load stops on an
  error box that reads exactly like a broken ini.
- `uninstall-map <name>` - take one back out again.
- `maps` - the map cache the engine would build: which maps can be started, and how to spell
  them on a command line.
"""

import argparse
import shutil
import sys
from pathlib import Path

from sage_live.launch.maps import load_map_cache
from sage_live.launch.runner import install_map_folder, user_files_dir
from sage_utils.cli import existing_dir, utf8_stdout


def _run_install_map(args: argparse.Namespace) -> int:
    installed = install_map_folder(
        args.folder,
        name=args.name,
        extras=tuple(args.extras),
        user_files=args.user_files,
    )
    print(f"installed {installed.path}")
    for path in installed.created[1:]:
        print(f"      and {path}")
    print(f"\n-file argument: {installed.argument}")
    print(f"map list name:  {installed.path.name}")
    return 0


def _run_uninstall_map(args: argparse.Namespace) -> int:
    target = (args.user_files or user_files_dir()) / "Maps" / args.name
    if not target.is_dir():
        print(f"nothing installed at {target}")
        return 1
    shutil.rmtree(target)
    print(f"removed {target}")
    return 0


def _run_maps(args: argparse.Namespace) -> int:
    entries = load_map_cache(install=args.install, mod=args.mod)
    startable = [e for e in entries if e.is_multiplayer]
    for entry in entries:
        if args.startable_only and not entry.is_multiplayer:
            continue
        flags = "mp" if entry.is_multiplayer else "  "
        print(f"  {flags}  {entry.num_players}p  {entry.name}")
    print(f"\n{len(entries)} cached, {len(startable)} startable with -file")
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage-test", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser(
        "install-map", help="copy a map folder into the game's user-files Maps directory"
    )
    install.add_argument("folder", type=existing_dir, help="the map's folder, holding <name>.map")
    install.add_argument(
        "--name",
        default=None,
        help="install under this name instead of the folder's own. REPLACES any folder of that "
        "name, so prefer a name the harness owns over a bare map name",
    )
    install.add_argument(
        "--extras",
        type=existing_dir,
        nargs="*",
        default=[],
        metavar="DIR",
        help="sibling folders the map.ini #includes, copied next to the map",
    )
    install.add_argument(
        "--user-files", type=Path, default=None, help="override the user-files directory"
    )
    install.set_defaults(func=_run_install_map)

    uninstall = subparsers.add_parser(
        "uninstall-map", help="remove a map installed into the user-files Maps directory"
    )
    uninstall.add_argument("name", help="the installed folder's name")
    uninstall.add_argument(
        "--user-files", type=Path, default=None, help="override the user-files directory"
    )
    uninstall.set_defaults(func=_run_uninstall_map)

    maps = subparsers.add_parser("maps", help="the map cache the engine would build")
    maps.add_argument("--install", type=existing_dir, default=None, help="a game install folder")
    maps.add_argument("--mod", type=existing_dir, default=None, help="an uncompiled mod tree")
    maps.add_argument(
        "--startable-only", action="store_true", help="omit maps the -file auto-start refuses"
    )
    maps.set_defaults(func=_run_maps)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
