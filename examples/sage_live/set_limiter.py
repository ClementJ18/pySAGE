"""Raise `TheGameEngine+0x0C`, the frame limiter, in a running game.

A `render-rate` binary carries the client rate and everything derived from it, but
`FramesPerSecondLimit` lives in Edain's `GameData` inside the `.big` archives, where no patch
reaches it - and that number is what lands in `TheGameEngine+0x0C`, which the `Sleep(0)` pace
targets. Edain sets it to 30. So a 60 fps build started cold paces its loop at 30 while every
constant says 60, and **the whole game runs at half speed** - measured 2.67 Hz logic against the
5.67 Hz it should have. Nothing looks broken; it just runs slow.

This writes that one field and nothing else, so a build can be tested at its intended pace. It is
a live poke: a restart undoes it, and the game has to be started before it can be applied. See
`render-rate.md` §9.3 for why the build should eventually carry this itself.

    python examples/sage_live/set_limiter.py 60
    python examples/sage_live/set_limiter.py --check

`sage_live`'s `ProcessMemory.write` is not enough here - it opens its handle without
`PROCESS_VM_OPERATION` - so the write goes through `set_render_rate.py`'s `Writer`, which is the
one place in this directory that asks for the access it needs.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # repo root on path
sys.path.insert(0, str(HERE))  # and the sibling scripts

from set_render_rate import Writer  # noqa: E402

from sage_live.backends.memory import ProcessMemory, find_game_processes  # noqa: E402

#: `TheGameEngine`, and the limiter `GlobalData`'s `FramesPerSecondLimit` is folded into.
THE_GAME_ENGINE = 0x00DE4324
MAX_FPS = 0x0C
#: The client rate the build was made with, for the mismatch warning.
CLIENT_RATE = 0x00D9F60C


def read_i32(memory: ProcessMemory, address: int) -> int | None:
    raw = memory.read(address, 4)
    return struct.unpack("<i", raw)[0] if raw else None


def engine_address(memory: ProcessMemory) -> int:
    raw = memory.read(THE_GAME_ENGINE, 4)
    if not raw:
        raise SystemExit("could not read TheGameEngine")
    engine = struct.unpack("<I", raw)[0]
    if not engine:
        raise SystemExit("TheGameEngine is null - attach after the game is past its splash")
    return engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="report the state, write nothing")
    group.add_argument("fps", type=int, nargs="?", help="what to set the limiter to")
    args = parser.parse_args()

    pids = find_game_processes()
    if not pids:
        raise SystemExit("no game.dat running")
    try:
        memory = ProcessMemory(pids[0])
    except PermissionError as exc:
        raise SystemExit(f"{exc}\nrun this from an elevated shell") from exc

    try:
        engine = engine_address(memory)
        limiter = read_i32(memory, engine + MAX_FPS)
        rate = read_i32(memory, CLIENT_RATE)
        print(f"game.dat pid {pids[0]}  TheGameEngine 0x{engine:08X}")
        print(f"  limiter  +0x0C          = {limiter}")
        print(f"  client rate [0x{CLIENT_RATE:08X}] = {rate}")
        if limiter != rate:
            slow = f"{limiter / rate:.2f}x" if limiter and rate else "the wrong"
            print(f"  ! they disagree - the game is running at {slow} speed")

        if args.check:
            return
        if args.fps is None:
            raise SystemExit("give an fps, or --check")
        if args.fps != rate:
            print(f"\n  ! {args.fps} is not the rate this binary was built for ({rate})")

        writer = Writer(pids[0])
        try:
            writer.write(engine + MAX_FPS, struct.pack("<i", args.fps), unprotect=False)
        finally:
            writer.close()
        print(f"\nlimiter {limiter} -> {read_i32(memory, engine + MAX_FPS)}")
    finally:
        memory.close()


if __name__ == "__main__":
    main()
