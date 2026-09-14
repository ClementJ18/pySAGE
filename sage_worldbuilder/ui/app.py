"""Desktop entry point of the map editor: `sage-worldbuilder [map] [-mod <folder>]...` or
`python -m sage_worldbuilder.ui [map] [-mod <folder>]...`, installed with the `worldbuilder` extra.
`-mod` mounts an unpacked mod above the install before anything opens, as the game's own switch
does; given more than once, the mods load in that order and a later one wins. A mod overlay
launches it through `main(extra_checks=...)` to add its own map rules to Generate Report."""

import argparse
import sys
import traceback
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

from sage_utils.extras import require_extra

if TYPE_CHECKING:
    from sage_worldbuilder.ui.validation import MapChecks


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sage-worldbuilder", allow_abbrev=False)
    parser.add_argument("map", nargs="?", type=Path, help="a .map file to open")
    parser.add_argument(
        "-mod",
        "--mod",
        dest="mods",
        action="append",
        default=[],
        metavar="FOLDER",
        help="an unpacked mod folder to load above the game install; repeat it to load several, "
        "a later one winning over an earlier one. A relative path is looked up in the user-data "
        "folder's Mods first, as the game does",
    )
    parser.add_argument(
        "-sagepatch",
        "--sagepatch",
        dest="sagepatch",
        type=Path,
        metavar="FILE",
        help="the .sagepatch of the patched game.dat the mod is written for: its INI fields are "
        "read, and Jump To Game applies its patches",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, extra_checks: "MapChecks | None" = None) -> None:
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    require_extra("worldbuilder", "sage-worldbuilder", "PyQt6", "pyBIG")
    # Imported after the check: both pull in PyQt6 at import time, which is exactly the failure
    # `require_extra` is here to report in plain language.
    from sage_utils.installs import user_data_dir  # noqa: PLC0415
    from sage_utils.widgets import run_app  # noqa: PLC0415
    from sage_worldbuilder.gamedata import resolve_mod_folder  # noqa: PLC0415
    from sage_worldbuilder.ui.window import (  # noqa: PLC0415
        APP_NAME,
        ICON_ANCHOR,
        ICON_FILE,
        MainWindow,
    )

    mods = [resolve_mod_folder(value, user_data_dir("rotwk")) for value in args.mods]
    for mod in mods:
        if not mod.is_dir():
            sys.exit(f"sage-worldbuilder: no mod folder at {mod}")
    sagepatch = args.sagepatch.resolve() if args.sagepatch is not None else None
    if sagepatch is not None and not sagepatch.is_file():
        sys.exit(f"sage-worldbuilder: no .sagepatch at {sagepatch}")
    # PyQt aborts the process on an exception escaping a Qt callback; report it instead, so one
    # faulty panel cannot take unsaved work down with it.
    sys.excepthook = report_unhandled
    run_app(
        lambda: MainWindow(
            initial_path=args.map, mods=mods, sagepatch=sagepatch, extra_checks=extra_checks
        ),
        icon_file=ICON_FILE,
        anchor=ICON_ANCHOR,
        app_name=APP_NAME,
    )


def report_unhandled(
    kind: type[BaseException], error: BaseException, trace: TracebackType | None
) -> None:
    text = "".join(traceback.format_exception(kind, error, trace))
    sys.stderr.write(text)
    # Qt is loaded by the time a Qt callback can fail.
    from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: PLC0415

    if QApplication.instance() is not None:
        QMessageBox.critical(
            None,
            "SAGE WorldBuilder",
            f"Something went wrong; the editor keeps running, but save your work.\n\n{text}",
        )


if __name__ == "__main__":
    main()
