"""`python -m sage_accel` - build the accelerator module and put it beside a game.

- `build [--out DIR]` - compile `sage_accel.dll` (needs the `accel` extra, i.e. `ziglang`).
- `install GAME_DIR [--dll PATH]` - copy a built module next to `GAME_DIR/game.dat`.

The module does nothing until `game.dat` carries the `accel-module` patch (`sage-patch apply`), and
the patched game runs as stock whenever the DLL is absent.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from sage_accel.build import DLL_NAME, build, install
from sage_utils.cli import existing_dir, existing_file

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sage_accel", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="compile sage_accel.dll")
    p_build.add_argument("--out", type=Path, default=Path("build"), help="output directory")

    p_install = sub.add_parser("install", help="copy sage_accel.dll next to a game.dat")
    p_install.add_argument("game_dir", type=existing_dir)
    p_install.add_argument("--dll", type=existing_file, default=Path("build") / DLL_NAME)

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            print(build(args.out))
        else:
            print(install(args.dll, args.game_dir))
    except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
