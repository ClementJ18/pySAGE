#!/usr/bin/env python3
"""Build the patched game.dat from the clean backup (thin CLI over the patching framework).

    OUT=game.dat python patch.py     # raise the CommandSet limit to 64 -> ./game.dat

Always patches from ``game.dat.backup`` (never edits it). ``OUT`` sets the output name
(default ``patched.dat``); ``COUNT`` sets the new limit (default 64, range 34..127).
"""

import logging
import os
import sys
from pathlib import Path

# Allow running as a plain script (`python patch.py`) even if the package isn't installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from sage_mods.edain.patching import CommandSetLimitPatch, apply_patches  # noqa: E402

HERE = Path(__file__).parent


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    src = HERE / "game.dat.backup"
    out = HERE / os.environ.get("OUT", "patched.dat")
    count = int(os.environ.get("COUNT", "64"))

    apply_patches(src, [CommandSetLimitPatch(count=count)], output=out)
    print(f"\nWROTE {out}  [N={count}]")


if __name__ == "__main__":
    main()
