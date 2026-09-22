"""Read the `perf-stage-readout` counter block out of a running game and print the profile.

`perf-stage-readout.md` §7 says what to do with the numbers and leaves the reading of them to a
client. This is that client. It attaches read-only with `OpenProcess` + `ReadProcessMemory` (the
same path `sage_live.backends.memory` uses - no injection, nothing written), finds the `.perfstg`
section in the mapped image, and takes **two samples a few seconds apart and subtracts**, because
the cave accumulates from process start and never resets.

The block's own layout is imported from the patch module, so this cannot drift from it.

What the columns mean:

  calls       how many times the scope was entered during the window
  incl ms     everything inside the scope, children included
  excl ms     the same minus the time its children owned
  ms/frame    exclusive, divided by the frames in the window
  calls/frame `MeshDX8Render` is per mesh - this column is the mesh count

Rows are labelled from `STAGE_SITES`, the patch's own call-site table, because the cave keys on a
return address rather than on a name pointer - four of the thirty sites build their name on the
stack, so the pointer is not a key. The two sites that share a stage's label are summed.

The frame count comes from a scope that is known to run exactly once per drawn frame
(`RenderViews`, falling back through `UpdateShadowMap` and `RenderUI`), so a per-frame figure
needs nothing from the engine and no guess about what a frame is.

Ticks are `QueryPerformanceCounter`; the frequency is system-wide invariant, so it is asked for
here rather than stored by the cave.

Run: python -m sage_patch.scripts.perf_stage_dump [--seconds N] [--pid N] [--csv FILE]
"""

from __future__ import annotations

import argparse
import ctypes
import struct
import sys
import time
from dataclasses import dataclass

from sage_live.backends.memory import MemorySource, ProcessMemory, find_game_processes
from sage_patch.addresses import IMAGE_BASE
from sage_patch.patches.perf_stage_readout import (
    BLOCK_MAGIC,
    OFF_DEPTH,
    OFF_OVERFLOW,
    OFF_SLOTS,
    OFF_SLOTS_USED,
    OFF_TABLE_FULL,
    OFF_UNBALANCED,
    SECTION_NAME,
    SLOT_CAPACITY,
    SLOT_SIZE,
    STAGE_SITES,
)
from sage_patch.pe import find as find_section
from sage_patch.pe import mapped_sections

#: Scopes that run once per drawn frame, best first. The window's frame count is whichever of
#: these was entered at all.
FRAME_SCOPES = ("RenderViews", "UpdateShadowMap", "RenderUI")


@dataclass(frozen=True)
class Slot:
    """One stage's counters, as the block holds them."""

    name: str
    calls: int
    inclusive: int
    exclusive: int


@dataclass(frozen=True)
class Sample:
    """A whole block, read at one instant."""

    tick: int
    depth: int
    slots_used: int
    overflow: int
    unbalanced: int
    table_full: int
    slots: dict[str, Slot]


def qpc_frequency() -> int:
    value = ctypes.c_longlong()
    ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(value))
    return value.value


def qpc() -> int:
    value = ctypes.c_longlong()
    ctypes.windll.kernel32.QueryPerformanceCounter(ctypes.byref(value))
    return value.value


def block_base(memory: MemorySource) -> int:
    """The `.perfstg` section's VA in the running process, checked against the magic.

    The image's headers are mapped at `IMAGE_BASE` (the engine has no ASLR), so the section table
    is read out of the process and the game.dat on disk is never opened.
    """
    section = find_section(mapped_sections(memory.read, IMAGE_BASE), SECTION_NAME)
    if section is None:
        raise SystemExit(
            f"{SECTION_NAME} is not in the running image - this game.dat does not carry "
            "perf-stage-readout. Apply it with: sage-patch apply perf-stage-readout"
        )
    head = memory.read(section.virtual_address, 0x10)
    if head is None:
        raise SystemExit(f"cannot read {section.virtual_address:#010x} - is the game still up?")
    magic, _version, capacity = struct.unpack_from("<III", head, 0)
    if magic != BLOCK_MAGIC:
        raise SystemExit(
            f"{SECTION_NAME} holds {magic:#010x}, expected {BLOCK_MAGIC:#010x} ('PSTG')"
        )
    if capacity != SLOT_CAPACITY:
        raise SystemExit(f"the block declares {capacity} slots, this reader knows {SLOT_CAPACITY}")
    return section.virtual_address


def read_sample(memory: MemorySource, base: int) -> Sample:
    """One whole block, with each slot labelled by the call site it keys on.

    A slot's key is a return address, so the label comes out of :data:`STAGE_SITES` and no string
    is read from the game at all. Four of the thirty sites share a label with another - the two
    `MeshDX8Render` sites and the two `MeshFXShader` ones - and those rows are **summed**, because
    what a profile wants is what the stage cost, not which of its two call sites paid.
    """
    size = OFF_SLOTS + SLOT_CAPACITY * SLOT_SIZE
    raw = memory.read(base, size)
    tick = qpc()
    if raw is None or len(raw) < size:
        raise SystemExit("the counter block vanished mid-read - the game exited")

    slots: dict[str, Slot] = {}
    for index in range(SLOT_CAPACITY):
        offset = OFF_SLOTS + index * SLOT_SIZE
        site, calls, inclusive, exclusive = struct.unpack_from("<IIQQ", raw, offset)
        if site == 0:
            continue
        name = STAGE_SITES.get(site, f"{site:#010x}")
        seen = slots.get(name)
        if seen is not None:
            calls += seen.calls
            inclusive += seen.inclusive
            exclusive += seen.exclusive
        slots[name] = Slot(name, calls, inclusive, exclusive)

    # The five counters are consecutive dwords, but each is read at its own named offset so
    # this stays correct if the block ever grows a field between them.
    depth, used, overflow, unbalanced, full = (
        struct.unpack_from("<I", raw, off)[0]
        for off in (OFF_DEPTH, OFF_SLOTS_USED, OFF_OVERFLOW, OFF_UNBALANCED, OFF_TABLE_FULL)
    )
    return Sample(tick, depth, used, overflow, unbalanced, full, slots)


def delta(first: Sample, second: Sample) -> list[Slot]:
    """What happened between two samples, as slots holding differences."""
    rows = []
    for name, later in second.slots.items():
        earlier = first.slots.get(name)
        calls = later.calls - (earlier.calls if earlier else 0)
        inclusive = later.inclusive - (earlier.inclusive if earlier else 0)
        exclusive = later.exclusive - (earlier.exclusive if earlier else 0)
        if calls > 0:
            rows.append(Slot(name, calls, inclusive, exclusive))
    rows.sort(key=lambda slot: slot.exclusive, reverse=True)
    return rows


def frame_count(rows: list[Slot]) -> int:
    by_name = {slot.name: slot for slot in rows}
    for name in FRAME_SCOPES:
        if name in by_name:
            return by_name[name].calls
    return 0


def report(rows: list[Slot], seconds: float, frequency: int, sample: Sample) -> None:
    frames = frame_count(rows)
    ms = 1000.0 / frequency
    total_exclusive = sum(slot.exclusive for slot in rows) * ms

    print(f"window {seconds:.2f}s   frames {frames}   ", end="")
    if frames:
        print(f"{frames / seconds:.1f} fps   frame budget {seconds * 1000 / frames:.2f} ms")
    else:
        print("no frame scope was entered - is the game at a menu, or minimised?")
    print(f"scopes accounted for {total_exclusive:.1f} ms of it\n")

    header = f"{'stage':<24}{'calls':>10}{'incl ms':>11}{'excl ms':>11}"
    if frames:
        header += f"{'ms/frame':>11}{'calls/frame':>13}"
    print(header)
    print("-" * len(header))
    for slot in rows:
        line = (
            f"{slot.name:<24}{slot.calls:>10}"
            f"{slot.inclusive * ms:>11.1f}{slot.exclusive * ms:>11.1f}"
        )
        if frames:
            line += f"{slot.exclusive * ms / frames:>11.3f}{slot.calls / frames:>13.1f}"
        print(line)

    notes = []
    if sample.overflow:
        notes.append(f"{sample.overflow} scopes entered past the nesting stack")
    if sample.unbalanced:
        notes.append(f"{sample.unbalanced} unbalanced exits")
    if sample.table_full:
        notes.append(f"{sample.table_full} names found no slot")
    if sample.depth:
        notes.append(f"depth was {sample.depth} at the last read")
    if notes:
        print("\nnotes: " + "; ".join(notes))
    print(f"\n{sample.slots_used} of {SLOT_CAPACITY} slots claimed since the process started.")


def write_csv(path: str, rows: list[Slot], seconds: float, frequency: int) -> None:
    frames = frame_count(rows)
    ms = 1000.0 / frequency
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("stage,calls,inclusive_ms,exclusive_ms,ms_per_frame,calls_per_frame\n")
        for slot in rows:
            per_frame = slot.exclusive * ms / frames if frames else 0.0
            calls_per_frame = slot.calls / frames if frames else 0.0
            handle.write(
                f"{slot.name},{slot.calls},{slot.inclusive * ms:.3f},"
                f"{slot.exclusive * ms:.3f},{per_frame:.4f},{calls_per_frame:.2f}\n"
            )
    print(f"\nwrote {path} ({len(rows)} stages, {frames} frames, {seconds:.2f}s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--seconds",
        type=float,
        default=10.0,
        help="how long to leave between the two samples (default 10)",
    )
    parser.add_argument("--pid", type=int, help="which game.dat, if several are running")
    parser.add_argument("--csv", help="also write the table to this file")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="take this many windows back to back, so a phase of the match can be followed",
    )
    args = parser.parse_args(argv)

    pid = args.pid
    if pid is None:
        found = find_game_processes()
        if not found:
            print("no game.dat is running", file=sys.stderr)
            return 1
        if len(found) > 1:
            print(f"several games are running: {found} - pass --pid", file=sys.stderr)
            return 1
        pid = found[0]

    frequency = qpc_frequency()
    memory = ProcessMemory(pid)
    try:
        base = block_base(memory)
        print(f"pid {pid}   {SECTION_NAME} at {base:#010x}   qpc {frequency / 1e6:.3f} MHz")
        first = read_sample(memory, base)
        for window in range(args.repeat):
            time.sleep(args.seconds)
            second = read_sample(memory, base)
            seconds = (second.tick - first.tick) / frequency
            rows = delta(first, second)
            if args.repeat > 1:
                print(f"\n=== window {window + 1} of {args.repeat}")
            print()
            report(rows, seconds, frequency, second)
            if args.csv:
                name = args.csv if args.repeat == 1 else f"{args.csv}.{window + 1}"
                write_csv(name, rows, seconds, frequency)
            first = second
    finally:
        memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
