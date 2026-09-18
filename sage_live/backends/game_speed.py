"""Run a game faster than it plays, by raising the frame cap the main loop paces itself to.

The simulation has no clock of its own. One pass of the main loop is one client frame and every
sixth ends a logic frame (`sage_patch/docs/render-rate.md` §3), so the simulation runs at the
loop's pace over six - and the loop paces itself to one number, `TheGameEngine`'s frame cap (§2).
Ten times the cap is ten times the game, with every duration still counted in logic frames:
nothing the simulation does changes, only how long the player waits for it. No code is written.

The cap's source is `GameData`'s `FramesPerSecondLimit`. The engine pushes it into the field
itself, and puts it back from there after a shell movie has raised it, so normal speed is restored
the same way and nothing has to be remembered: a controller that died with the game fast leaves a
game the next attach reads as fast and can set back.

The loop draws every frame it runs, so ten times the pace is also ten times the frames drawn. A
machine that cannot draw that many gets as fast as it can draw rather than ten times; measure the
logic frame against the wall clock to know which.
"""

from __future__ import annotations

import struct
from collections.abc import Callable

from sage_live.backends.live_patch import LivePatchError, LiveProcess
from sage_patch.addresses import (
    GAME_ENGINE,
    GAME_ENGINE_MAX_FPS,
    GLOBAL_DATA,
    GLOBAL_DATA_FPS_LIMIT,
)

__all__ = ["FAST_FORWARD", "base_rate", "set_speed", "speed"]

#: The multiplier the editor's fast-forward runs at.
FAST_FORWARD = 10

Reader = Callable[[int, int], bytes | None]


def _u32(read: Reader, address: int) -> int | None:
    raw = read(address, 4)
    return struct.unpack("<I", raw)[0] if raw else None


def _cap_address(read: Reader) -> int | None:
    engine = _u32(read, GAME_ENGINE)
    return engine + GAME_ENGINE_MAX_FPS if engine else None


def base_rate(read: Reader) -> int | None:
    """`FramesPerSecondLimit` - the cap the game runs at normal speed - or None where unreadable."""
    data = _u32(read, GLOBAL_DATA)
    return _u32(read, data + GLOBAL_DATA_FPS_LIMIT) if data else None


def speed(read: Reader) -> int:
    """How many times faster than normal the game is paced: 1 at normal speed, and 1 wherever the
    cap or its source cannot be read or the cap is not a whole multiple of the source."""
    base = base_rate(read)
    address = _cap_address(read)
    cap = _u32(read, address) if address is not None else None
    if not base or not cap or cap % base:
        return 1
    return max(1, cap // base)


def set_speed(process: LiveProcess, multiplier: int) -> None:
    """Pace the game at `multiplier` times normal; 1 puts it back to `FramesPerSecondLimit`."""
    if multiplier < 1:
        raise ValueError(f"a speed multiplier must be 1 or more, not {multiplier}")
    base = base_rate(process.read)
    address = _cap_address(process.read)
    if base is None or address is None:
        raise LivePatchError("the game engine is not up yet")
    if base == 0:
        raise LivePatchError("the game sets no frame cap, so it already runs as fast as it can")
    if not process.write(address, struct.pack("<I", base * multiplier)):
        raise LivePatchError("writing the frame cap failed")
