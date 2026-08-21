"""Flip a running game between client rates, so one match can be measured at both.

`render_rate_probe.py` compares 30 fps against 60. Doing that by patching `game.dat` and
relaunching gives two *different* matches - different units, different camera, different
motion - and the numbers that matter (distinct interpolated matrices per logic frame) are not
comparable across them. This applies the same edits to the live process instead, so the A and
the B are the same match seconds apart.

**This writes to a running game, including five bytes of `.text`.** Nothing here touches
`game.dat` on disk, so the worst case is a crashed game and a lost match, never a broken
install. The edits are exactly the `render-rate` patch's, plus the frame
limiter, and every site is verified against its expected current bytes before anything is
written - a site that does not match aborts the whole flip before the first write.

    python examples/sage_live/set_render_rate.py --check
    python examples/sage_live/set_render_rate.py --to 60
    python examples/sage_live/set_render_rate.py --to 30      # put it back

The order is chosen so a torn write leaves the game *slow*, never fast: the wrap moves before
the rate it divides, and the frame limiter moves last. A game caught mid-flip simulates at half
speed for a few milliseconds and then converges.

Every `.text` write is a **single byte replacing an immediate operand** - no instruction changes
length, and x86 keeps instruction caches coherent, so a thread executing that instruction while
it is written reads either the old operand or the new one. That is the reason this is a
reasonable thing to do at all; it would not be if the edits resized anything or spanned bytes.

`TheGameEngine+0x0C` (the limiter) is written directly rather than through `GameData
FramesPerSecondLimit`, which lives in three `.big` archives. The engine's own set-frame-rate
script action writes the same field, so this is not a novel operation - but a shell or cinematic
transition (`0x0091B6DC` / `0x0091B7AA`) rewrites it, so re-run `--check` if one happens.
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.backends.memory import ProcessMemory, find_game_processes  # noqa: E402

LOGIC_RATE = 0x00D9F608
CLIENT_RATE = 0x00D9F60C
# The divisor this build's latch predicate uses instead of the logic rate (see `latch_divisor`).
LATCH_DIVISOR = 0x00ECA400
# `1000 / clientRate`, milliseconds per client frame. A **CRT static initialiser**
# (`0x00BC146C`), so it is computed once at startup and a file build gets it right while a live
# poke of the client rate leaves it stale - which made the render clock run at 2.06x real time
# and every effect with it. Poking it too is what makes the live flip faithful. It is not the
# only startup-derived value keyed to the client rate, only the one measured to matter.
MS_PER_CLIENT_FRAME = 0x00DC7A8C
THE_GAME_ENGINE = 0x00DE4324
ENGINE_MAX_FPS = 0x0C
ENGINE_RATIO = 0x38
ENGINE_RATES_CHANGED = 0x40  # the latch that lets 0x0063260F recompute the ratio

# The imm8 of a 3-byte `cmp r32, imm8` / `imul r32, r32, imm8` sits at +2.
WRAP_IMM = 0x0063264A + 2
GATE_IMM = 0x00632604 + 2
STRIDE_IMMS = (0x0062ECC6 + 2, 0x00632631 + 2, 0x00632ACF + 2)

PAGE_EXECUTE_READWRITE = 0x40
STOCK_FPS = 30


def derived_floats(fps: int) -> dict[int, bytes]:
    """The four rate-derived constants, folded in double then narrowed - see `render-rate`."""
    return {
        0x00D9F620: struct.pack("<f", 1000.0 / fps),
        0x00D9F624: struct.pack("<f", fps * 0.001),
        0x00D9F628: struct.pack("<f", float(fps)),
        0x00D9F62C: struct.pack("<f", 1.0 / fps),
    }


def latch_divisor(fps: int) -> int:
    """`[0x00ECA400]`, chosen so the once-per-logic-frame latch keeps firing.

    `0x0063252F` answers `subFrame == 6 / (clientRate / [0x00ECA400])`, or `subFrame == 1` once
    that quotient reaches 6. **Sub-frame 1 is never observable by client code on this build**:
    the wrap sets the counter to 1 and the always-running catch-up loop bumps it to 2 inside the
    same logic step, before `GameClient::update` next runs. Measured live 2026-08-20 - the
    counter was sampled every client frame for 373 frames across both rates and took the values
    2..6 at rate 30 and 2..12 at rate 60, never 1.

    So a predicate answering 1 never fires, and every `previous = current` latch behind it
    freezes - which is the stuck-animation symptom that got the render-rate patch withdrawn.
    Stock 30 lands on `30/8 = 3` and therefore on sub-frame 2, which *is* observable; raising the
    rate to 60 pushes the quotient to 7 and silently switches the answer to 1.

    Keeping the quotient at 3 keeps the answer at 2 at any rate. The stock 8 is preserved
    wherever it already gives 3, so a 30 fps binary stays byte-identical to stock.
    """
    return 8 if fps // 8 == 3 else fps // 3


def plan(fps: int) -> list[tuple[int, bytes, bool, str]]:
    """Every write for `fps`, as (address, bytes, is_code, label), in the order to apply them.

    The wrap first: raising it before the rate it divides makes the simulation briefly *slower*
    than intended rather than faster, and a slow tick is recoverable where a fast one desyncs
    anything watching. The limiter last, for the same reason.
    """
    ratio = fps // 5
    stride = max(10, ratio)
    writes: list[tuple[int, bytes, bool, str]] = [
        (WRAP_IMM, bytes([ratio]), True, "the wrap"),
        (GATE_IMM, bytes([1 if fps != STOCK_FPS else 6]), True, "recompute gate"),
    ]
    writes += [(va, bytes([stride]), True, "timecode stride") for va in STRIDE_IMMS]
    writes.append((LATCH_DIVISOR, struct.pack("<i", latch_divisor(fps)), False, "latch divisor"))
    writes.append(
        (MS_PER_CLIENT_FRAME, struct.pack("<i", 1000 // fps), False, "ms per client frame")
    )
    writes.append((CLIENT_RATE, struct.pack("<i", fps), False, "client rate"))
    writes += [(va, new, False, f"float 0x{va:08X}") for va, new in derived_floats(fps).items()]
    return writes


class Writer:
    """Writes to the target, lifting page protection for the ones that land in `.text`.

    A second handle rather than `ProcessMemory`'s: `VirtualProtectEx` needs
    `PROCESS_VM_OPERATION`, and reaching into another object's private handle to get it would
    make this script's requirements invisible at the point they are asked for.
    """

    _ACCESS = 0x0008 | 0x0010 | 0x0020 | 0x0400  # VM_OPERATION | VM_READ | VM_WRITE | QUERY_INFO

    # Declared rather than left to inference, as in `ProcessMemory`: everything below the
    # platform check is unreachable to a type checker running as Linux, so the assignments there
    # give these no type at all and every use in the methods below becomes an error.
    _k32: ctypes.CDLL  # a `WinDLL` on Windows, which `CDLL` is the cross-platform spelling of
    _handle: int

    def __init__(self, pid: int) -> None:
        if sys.platform != "win32":
            raise SystemExit(f"This writes to a running Windows game; this is {sys.platform}.")
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.OpenProcess.restype = ctypes.c_void_p
        self._k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        self._k32.VirtualProtectEx.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        )
        self._k32.WriteProcessMemory.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        )
        handle = self._k32.OpenProcess(self._ACCESS, 0, pid)
        if not handle:
            err = ctypes.get_last_error()
            hint = (
                " - the game runs as administrator, so this shell must be elevated"
                if err == 5
                else ""
            )
            raise SystemExit(f"OpenProcess({pid}) failed with error {err}{hint}")
        self._handle = handle

    def write(self, address: int, data: bytes, unprotect: bool) -> None:
        old = ctypes.c_uint32()
        if unprotect:
            ok = self._k32.VirtualProtectEx(
                self._handle,
                ctypes.c_void_p(address),
                len(data),
                PAGE_EXECUTE_READWRITE,
                ctypes.byref(old),
            )
            if not ok:
                raise SystemExit(f"VirtualProtectEx at 0x{address:08X} failed")
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        put = ctypes.c_size_t()
        ok = self._k32.WriteProcessMemory(
            self._handle, ctypes.c_void_p(address), buf, len(data), ctypes.byref(put)
        )
        if unprotect:
            restored = ctypes.c_uint32()
            self._k32.VirtualProtectEx(
                self._handle, ctypes.c_void_p(address), len(data), old, ctypes.byref(restored)
            )
        if not ok or put.value != len(data):
            raise SystemExit(f"WriteProcessMemory at 0x{address:08X} failed")

    def close(self) -> None:
        self._k32.CloseHandle(ctypes.c_void_p(self._handle))


def current_state(memory: ProcessMemory) -> tuple[int, int | None, list[str]]:
    """What the process is carrying: (client rate, agreed rate, mismatching sites).

    The agreed rate is None when the sites do not all match the client rate, which is the state
    a half-applied flip leaves and the one thing that must never be written over.
    """
    rate_raw = memory.read(CLIENT_RATE, 4)
    if rate_raw is None:
        raise SystemExit("cannot read the client rate - is this shell elevated?")
    rate = struct.unpack("<i", rate_raw)[0]
    mismatches = []
    for address, expected, _is_code, label in plan(rate):
        got = memory.read(address, len(expected))
        if got != expected:
            got_hex = got.hex() if got else "unreadable"
            mismatches.append(f"{label} @0x{address:08X}: expected {expected.hex()}, got {got_hex}")
    return rate, (rate if not mismatches else None), mismatches


def report(memory: ProcessMemory) -> None:
    rate, agreed, mismatches = current_state(memory)
    logic_raw = memory.read(LOGIC_RATE, 4)
    logic = struct.unpack("<i", logic_raw)[0] if logic_raw else None
    engine_raw = memory.read(THE_GAME_ENGINE, 4)
    engine = struct.unpack("<I", engine_raw)[0] if engine_raw else 0
    max_fps = ratio = None
    if engine:
        max_raw = memory.read(engine + ENGINE_MAX_FPS, 4)
        ratio_raw = memory.read(engine + ENGINE_RATIO, 4)
        max_fps = struct.unpack("<i", max_raw)[0] if max_raw else None
        ratio = struct.unpack("<i", ratio_raw)[0] if ratio_raw else None

    print(f"client rate {rate}, logic rate {logic}")
    print(f"  TheGameEngine+0x0C limiter = {max_fps}   +0x38 ratio = {ratio}")
    if mismatches:
        print("  MIXED STATE - these sites do not match the client rate:")
        for line in mismatches:
            print(f"    {line}")
    else:
        print(f"  all {len(plan(rate))} sites agree on {agreed} fps")


def apply(memory: ProcessMemory, writer: Writer, fps: int) -> None:
    """Verify every site against its current rate, then write the new one and the limiter."""
    _rate, have, mismatches = current_state(memory)
    if have is None:
        print("refusing to write over a mixed state:")
        for line in mismatches:
            print(f"  {line}")
        raise SystemExit("restore the game (restart it) before flipping again")
    if have == fps:
        print(f"already at {fps} fps; nothing to do")
        return

    logic_raw = memory.read(LOGIC_RATE, 4)
    if logic_raw is None or struct.unpack("<i", logic_raw)[0] != 5:
        raise SystemExit("the logic rate is not 5; `ratio = fps / 5` is wrong for this build")

    for address, data, is_code, label in plan(fps):
        writer.write(address, data, unprotect=is_code)
        print(f"  ok  0x{address:08X}  {label}")

    engine_raw = memory.read(THE_GAME_ENGINE, 4)
    if engine_raw:
        engine = struct.unpack("<I", engine_raw)[0]
        # The ratio is written directly and the "rates changed" latch set, so the engine's own
        # recompute at 0x0063260F converges on the next logic frame rather than whenever the
        # latch happens to be set.
        writer.write(engine + ENGINE_RATIO, struct.pack("<i", fps // 5), unprotect=False)
        writer.write(engine + ENGINE_RATES_CHANGED, b"\x01", unprotect=False)
        writer.write(engine + ENGINE_MAX_FPS, struct.pack("<i", fps), unprotect=False)
        print(f"  ok  limiter and ratio on TheGameEngine 0x{engine:08X}")
    print(f"\nnow at {fps} fps (ratio {fps // 5})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="report the state, write nothing")
    group.add_argument("--to", type=int, help="client rate to switch to; a multiple of 5")
    args = parser.parse_args()

    pids = find_game_processes()
    if not pids:
        raise SystemExit("no game.dat running")
    try:
        memory = ProcessMemory(pids[0])
    except PermissionError as exc:
        raise SystemExit(f"{exc}\nrun this from an elevated shell") from exc

    print(f"game.dat pid {pids[0]}")
    if args.check:
        report(memory)
        memory.close()
        return

    if args.to % 5 or not (STOCK_FPS <= args.to <= 635):
        raise SystemExit(f"--to must be a multiple of 5 in [{STOCK_FPS}, 635]")
    report(memory)
    print()
    writer = Writer(pids[0])
    try:
        apply(memory, writer, args.to)
    finally:
        writer.close()
        memory.close()


if __name__ == "__main__":
    main()
