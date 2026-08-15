"""Read the `hero-mana` diagnostic ring out of a running game.

Only useful against a `game.dat` patched with ``HeroManaPatch(trace=True)``. The patch records one
record per special-power activation into a ring in its own cave; this prints them in order, newest
last, and can follow the ring as you play.

    python tools/hero_mana_trace.py            # dump what is there, then follow
    python tools/hero_mana_trace.py --once     # dump and exit

**Run it elevated** - `game.dat` runs as administrator, and an unelevated reader gets
`ERROR_ACCESS_DENIED` on `PROCESS_VM_READ`.

What the tags mean, and what each answers:

``DISPATCH v0/v1/v2``
    An `Object::doSpecialPower*` variant was reached. **Count these per cast.** One means the
    charge sits on the click; two means the fire path comes back through here and the charge can
    simply move to the second.

``SPEND-ENTER``
    The charge routine ran, with the final template and the `ManaCost` it read. A cast that
    produces no `SPEND-ENTER` never reached the charge at all; one with `cost=0` reached it but
    the template carries no cost - two very different bugs.

``SPEND``
    The affordability decision, with what it costs and what the caster had.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

from sage_live import ProcessMemory, find_game_processes
from sage_patch.patches.experimental import hero_mana as hm
from sage_patch.patches.experimental.hero_mana import SECTION_NAME, TRACE_RING, TRACE_STRIDE
from sage_patch.pe import find, mapped_sections

TAGS = {
    0x10: "DISPATCH v0 (doSpecialPower)",
    0x11: "DISPATCH v1 (atLocation)",
    0x12: "DISPATCH v2 (atObject)",
    0x20: "SPEND-ENTER",
    0x21: "SPEND",
    0x30: "ABILITY-FIRE",
}


def cave_base(memory: ProcessMemory) -> tuple[int, int, int]:
    """``(trace index VA, entries VA, section base)`` for the patch's cave in the live process.

    Found through the mapped PE headers rather than assumed, so it does not matter what else has
    been appended to the binary.
    """
    sections = mapped_sections(memory.read, 0x400000)
    section = find(sections, SECTION_NAME)
    if section is None:
        raise SystemExit(
            f"the running game has no {SECTION_NAME} section - it is not the patched build"
        )
    # The layout constants are private to the patch; take them from it rather than restating.
    base = section.virtual_address
    return base + hm._TRACE_INDEX_OFF, base + hm._TRACE_ENTRIES_OFF, base  # noqa: SLF001


def read_records(memory: ProcessMemory, index_va: int, entries_va: int, since: int):
    """Records written since the ``since`` counter, oldest first, with the new counter."""
    raw = memory.read(index_va, 4)
    if raw is None:
        raise SystemExit("cannot read the trace index - is the reader elevated?")
    total = struct.unpack("<I", raw)[0]
    if total == since:
        return [], total
    first = max(since, total - TRACE_RING)
    out = []
    for counter in range(first, total):
        slot = counter % TRACE_RING
        blob = memory.read(entries_va + slot * TRACE_STRIDE, TRACE_STRIDE)
        if blob is None or len(blob) < TRACE_STRIDE:
            continue
        frame, tag, a, b, c = struct.unpack("<IIIII", blob)
        out.append((counter, frame, tag, a, b, c))
    return out, total


def describe(record) -> str:
    counter, frame, tag, a, b, c = record
    name = TAGS.get(tag, f"tag {tag:#x}")
    if tag == 0x20:
        detail = f"template={a:#010x} ManaCost={b} object={c:#010x}"
    elif tag == 0x21:
        detail = f"cost={a / 100:g} available={b / 100:g}"
        detail += "  -> CHARGED" if b >= a else "  -> REFUSED"
    elif 0x10 <= tag <= 0x12 or tag == 0x30:
        detail = f"template={a:#010x} object={b:#010x}"
    else:
        detail = f"a={a:#x} b={b:#x} c={c:#x}"
    return f"[{counter:>5}] frame {frame:>7}  {name:<28} {detail}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="dump and exit instead of following")
    parser.add_argument("--pid", type=int, help="attach to this pid instead of searching")
    args = parser.parse_args(argv)

    pids = [args.pid] if args.pid else find_game_processes()
    if not pids:
        print("no game.dat process found - start the game first", file=sys.stderr)
        return 1

    memory = ProcessMemory(pids[0])
    try:
        index_va, entries_va, base = cave_base(memory)
        print(f"attached to pid {pids[0]}; {SECTION_NAME} at {base:#010x}")
        print("cast something. Ctrl-C to stop.\n")
        seen = 0
        # Start from whatever is already in the ring, so a cast before attaching is not lost.
        while True:
            records, seen = read_records(memory, index_va, entries_va, seen)
            for record in records:
                print(describe(record))
            if args.once:
                return 0
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    finally:
        memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
