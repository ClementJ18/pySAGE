"""Every site in `game.dat` whose behaviour depends on the CLIENT frame rate.

`render-rate.md` §5.3 promised this sweep and never ran it; §8 then removed the patch on the
strength of a claim - "a great deal of client content is authored in client frames" - that was
argued rather than enumerated. This enumerates it.

Six families, each recovered by a rule that is checkable rather than by pattern-guessing:

  A  readers of `GameClient::getFrame()`  - the client frame reaching client code
  B  readers of the rate block            - the ten derived constants at 0x00D9F608
  C  unrescaled rate constants            - 1/30 and 33.33 living OUTSIDE that block
  D  readers of the sub-frame state       - TheGameEngine +0x34 / +0x38 / +0x3C
  E  client-frame-valued globals          - the frame stamps that bypass the getter
  F  the pacing helpers                   - callers of the predicate, the alpha, the timecode

A site is classified by decoding forward from it, not by where it sits, so the verdict column
says what the code DOES with the frame number:

  MODULUS(n)   frame % n  - a cadence that assumes a rate; wrong at any other rate
  MODULUS(mem) frame % [x] - derives its cadence; correct at every rate if [x] is the rate
  BITMASK(m)   frame & m  - the same thing written cheaply; a power-of-two cadence
  DELTA        frame - stored - a duration in client frames; wrong if compared to a constant
  DEADLINE     frame + n  - a due-date in client frames; wrong by the same factor
  SCALE        the frame reaches float arithmetic; check the constant it meets
  STAMP        stored, not measured - correct at every rate
  PASSTHROUGH  handed to a callee; the verdict belongs to the callee
  REVIEW       none of the above matched; read it by hand

Run: python sage_patch/scripts/census_client_rate.py [--md] [path-to-game.dat]
"""

from __future__ import annotations

import bisect
import struct
import sys
from collections import defaultdict

import pefile
from capstone import CS_ARCH_X86, CS_MODE_32, Cs, x86

DEFAULT_PATH = (
    r"C:\Users\Clement\Documents\GitHub\pySAGE"
    r"\sage_mods\edain\patching\engine\game.dat.backup"
)

# The engine's own names for what this census is about.
THE_GAME_CLIENT = 0x00DE4388
THE_GAME_ENGINE = 0x00DE4324
GAMECLIENT_VTABLE = 0x00BDA6E0
GET_FRAME_SLOT = 0x7C  # GameClient::getFrame - `mov eax, [ecx+0x10]; ret`
SET_FRAME_SLOT = 0x38  # GameClient::setFrame - the counter's only writer

LOGIC_RATE = 0x00D9F608
CLIENT_RATE = 0x00D9F60C
RATE_BLOCK = {
    0x00D9F608: "logic rate (5)",
    0x00D9F60C: "client rate (30)",
    0x00D9F610: "logic/1000",
    0x00D9F614: "1000/logic",
    0x00D9F618: "(float)logic",
    0x00D9F61C: "1/logic",
    0x00D9F620: "1000/client",
    0x00D9F624: "client/1000",
    0x00D9F628: "(float)client",
    0x00D9F62C: "1/client",
}

# Sub-frame state on TheGameEngine, from render-rate.md §3.
ENGINE_FIELDS = {0x34: "sub-frame counter", 0x38: "ratio client/logic", 0x3C: "interpolation alpha"}

# `+0x34` is never reached through a fresh load of the global - the two functions that own it
# hold TheGameEngine in a register for their whole body, so it has to be swept by range.
ENGINE_OWNERS = (
    (0x006325A0, 0x00632708, "sub-frame advance"),
    (0x006329B0, 0x00632B11, "logic step"),
    (0x0063A49C, 0x0063A520, "GameEngine ctor"),
)

# Globals that hold a client frame number, so their readers are rate-dependent too.
FRAME_GLOBALS = {
    0x00D9F6F8: "last client frame the drawable pass ran",
    0x00D98C8C: "last client frame W3DDisplay::draw ran",
    0x00DE4308: "client frame stamped when the tick was skipped",
}

# The three helpers render-rate.md turns on.
SUBFRAME_PREDICATE = 0x0063252F
ALPHA_RECOMPUTE = 0x0063256F
TIMECODE_SINK = 0x006251A3

# Rate-derived float values that must not appear as hardcoded literals. `distinctive` says
# whether the value can plausibly mean anything else: 0.0333 and 33.33 are the client rate and
# nothing else, while 30.0 and 0.03 are values a program holds for a hundred unrelated reasons,
# so their hits are candidates to read rather than sites to rescale.
SUSPECT_FLOATS = {
    "1/30": (1.0 / 30.0, True),
    "1000/30": (1000.0 / 30.0, True),
    "30.0": (30.0, False),
    "30/1000": (30.0 / 1000.0, False),
}

# The shape of a CRT static initialiser deriving a file-scope global from the client rate.
STATIC_INIT_SHAPE = ("cdq", "sub", "sar")


class Image:
    """A PE32 image with a linear-sweep instruction index over .text."""

    def __init__(self, path: str) -> None:
        pe = pefile.PE(path, fast_load=True)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.data = open(path, "rb").read()
        self.sections = [
            (
                s.Name.rstrip(b"\x00").decode("latin1"),
                self.base + s.VirtualAddress,
                s.PointerToRawData,
                s.SizeOfRawData,
            )
            for s in pe.sections
        ]
        self.text = next(s for s in self.sections if s[0] == ".text")
        self.md = Cs(CS_ARCH_X86, CS_MODE_32)
        self.md.detail = True
        self._sweep()

    def off_to_va(self, off: int) -> int | None:
        for _, va0, fo, fs in self.sections:
            if fo <= off < fo + fs:
                return va0 + (off - fo)
        return None

    def va_to_off(self, va: int) -> int | None:
        for _, va0, fo, fs in self.sections:
            if va0 <= va < va0 + fs:
                return fo + (va - va0)
        return None

    def read(self, va: int, n: int) -> bytes | None:
        off = self.va_to_off(va)
        return self.data[off : off + n] if off is not None else None

    def dword(self, va: int) -> int | None:
        b = self.read(va, 4)
        return struct.unpack("<I", b)[0] if b else None

    def _sweep(self) -> None:
        """Decode every instruction in .text, resuming past bytes that do not decode.

        A single `md.disasm` call stops dead at the first undecodable byte - which in this
        image is 43k instructions out of 2.7M. Resuming is what makes the index complete.
        """
        _, va0, fo, fs = self.text
        code = self.data[fo : fo + fs]
        self.insns: dict[int, tuple[str, str, int]] = {}
        self.by_disp: dict[int, list[int]] = defaultdict(list)
        self.by_imm: dict[int, list[int]] = defaultdict(list)
        pos = 0
        while pos < len(code):
            reached = 0
            for ins in self.md.disasm(code[pos:], va0 + pos):
                reached = ins.address + ins.size - va0
                self.insns[ins.address] = (ins.mnemonic, ins.op_str, ins.size)
                for op in ins.operands:
                    if op.type == x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                        self.by_disp[op.mem.disp & 0xFFFFFFFF].append(ins.address)
                    elif op.type == x86.X86_OP_IMM:
                        self.by_imm[op.imm & 0xFFFFFFFF].append(ins.address)
            pos = max(reached, pos + 1)
        self.ordered = sorted(self.insns)

    def refs(self, value: int) -> list[int]:
        return sorted(set(self.by_disp.get(value, [])) | set(self.by_imm.get(value, [])))

    def forward(self, va: int, count: int) -> list[tuple[int, str, str]]:
        i = bisect.bisect_left(self.ordered, va)
        return [(k, *self.insns[k][:2]) for k in self.ordered[i + 1 : i + 1 + count]]

    def callers(self, target: int) -> list[int]:
        _, va0, fo, fs = self.text
        out = []
        for i in range(fo, fo + fs - 5):
            if self.data[i] == 0xE8:
                rel = struct.unpack("<i", self.data[i + 1 : i + 5])[0]
                va = self.off_to_va(i)
                if va is not None and va + 5 + rel == target:
                    out.append(va)
        return out


def virtual_calls(img: Image, global_va: int, slot: int) -> list[int]:
    """Sites doing `mov ecx,[global]; mov eax,[ecx]; call [eax+slot]` - a devirtualised call."""

    want = f"ecx, dword ptr [0x{global_va:x}]"
    tail = "dword ptr [eax]" if slot == 0 else f"dword ptr [eax + 0x{slot:x}]"
    out = []
    for va in img.refs(global_va):
        mnem, ops, _ = img.insns[va]
        if mnem != "mov" or ops != want:
            continue
        i = bisect.bisect_left(img.ordered, va)
        nxt = img.ordered[i + 1 : i + 3]
        if len(nxt) < 2:
            continue
        if img.insns[nxt[0]][:2] != ("mov", "eax, dword ptr [ecx]"):
            continue
        if img.insns[nxt[1]][0] == "call" and img.insns[nxt[1]][1] == tail:
            out.append(nxt[1])
    return out


def classify(img: Image, site: int) -> tuple[str, str]:
    """Decode forward from a call that returned the client frame in eax.

    Returns (verdict, evidence). The first shape that matches wins, because these shapes are
    what the value is FOR - a modulus is a cadence, a subtraction is a duration, a lone store
    is a stamp.
    """
    ahead = img.forward(site, 8)
    pending_imm: int | None = None
    signals: dict[str, str] = {}
    # The frame comes back in eax and may be moved on; only instructions touching a register
    # that still holds it say anything about the frame. Without this the window's unrelated
    # pointer arithmetic gets read as a duration.
    holding = {"eax", "al", "ax"}

    def note(kind: str, evidence: str) -> None:
        signals.setdefault(kind, evidence)

    def touches(ops: str) -> bool:
        return any(r in ops.split() or ops.startswith(r + ",") or f" {r}" in ops for r in holding)

    for _, mnem, ops in ahead:
        lhs = ops.split(",")[0].strip()
        if mnem == "mov" and ops.endswith(", eax") and lhs.startswith("e") and "[" not in lhs:
            holding.add(lhs)
        if mnem == "push":
            try:
                pending_imm = int(ops, 0)
            except ValueError:
                pending_imm = None
            note("PASSTHROUGH", f"{mnem} {ops}")
        elif mnem in ("div", "idiv"):
            if ops.startswith("dword ptr ["):
                mem = ops.split("[")[1].split("]")[0]
                kind = "MODULUS(rate)" if mem == f"0x{CLIENT_RATE:x}" else "MODULUS(mem)"
                note(kind, f"{mnem} {ops}")
            elif pending_imm is not None:
                note(f"MODULUS({pending_imm})", f"{mnem} {ops} ; = {pending_imm}")
            else:
                note("MODULUS(reg)", f"{mnem} {ops}")
        elif mnem == "test" and touches(ops):
            rhs = ops.partition(", ")[2]
            if lhs != rhs:  # `test x, x` is a null check on the return, not a cadence
                note(f"BITMASK({rhs})", f"{mnem} {ops}")
        elif mnem in ("sub", "cmp") and touches(ops):
            note("DELTA", f"{mnem} {ops}")
        elif mnem == "add" and lhs in holding:
            note("DEADLINE", f"{mnem} {ops}")
        elif mnem in ("fmul", "fimul", "mulss", "addss", "fild", "cvtsi2ss"):
            note("SCALE", f"{mnem} {ops}")
        elif mnem == "mov" and ops.endswith(", eax"):
            note("STAMP", f"{mnem} {ops}")
        elif mnem == "call":
            note("PASSTHROUGH", f"{mnem} {ops}")

    for kind in sorted(signals, key=_precedence):
        return kind, signals[kind]
    return "REVIEW", "; ".join(f"{m} {o}" for _, m, o in ahead[:3])


_ORDER = ("MODULUS", "BITMASK", "DEADLINE", "DELTA", "SCALE", "STAMP", "PASSTHROUGH")


def _precedence(kind: str) -> int:
    """A modulus outranks a subtraction outranks a store: the strongest statement the code
    makes about the frame number is the one that decides whether the rate matters."""
    return _ORDER.index(kind.split("(")[0])


def static_inits(img: Image, refs: list[int]) -> int:
    """How many of these refs are a CRT static initialiser rather than runtime code.

    `global = clientRate / 2`, emitted once per translation unit that includes the header.
    They recompute from the patched constant at startup, so they follow a rescale for free -
    which is why they must be counted out before the raw ref count means anything.
    """
    n = 0
    for va in refs:
        ahead = [m for _, m, _ in img.forward(va, 3)]
        if tuple(ahead) == STATIC_INIT_SHAPE:
            n += 1
    return n


def float_literals(img: Image, value: float) -> list[tuple[int, list[int]]]:
    """Every referenced 4-byte float in the image equal to `value`."""
    needle = struct.pack("<f", value)
    out = []
    i = 0
    while True:
        i = img.data.find(needle, i)
        if i < 0:
            break
        va = img.off_to_va(i)
        if va is not None:
            refs = img.refs(va)
            if refs:
                out.append((va, refs))
        i += 1
    return out


def field_reads(img: Image, global_va: int, field: int) -> list[int]:
    """Sites loading `[global]` and then touching `+field` on it within a few instructions."""

    out = []
    for va in img.refs(global_va):
        mnem, ops, _ = img.insns[va]
        if mnem != "mov" or f"[0x{global_va:x}]" not in ops:
            continue
        reg = ops.split(",")[0].strip()
        if not reg.startswith("e"):
            continue
        i = bisect.bisect_left(img.ordered, va)
        for k in img.ordered[i + 1 : i + 5]:
            if f"[{reg} + 0x{field:x}]" in img.insns[k][1]:
                out.append(k)
                break
    return out


def report(img: Image, markdown: bool) -> None:
    def head(title: str) -> None:
        print(("\n## " if markdown else "\n=== ") + title + ("" if markdown else " ==="))

    def table(rows: list[tuple[str, ...]], cols: tuple[str, ...]) -> None:
        if markdown:
            print("| " + " | ".join(cols) + " |")
            print("|" + "|".join("---" for _ in cols) + "|")
            for r in rows:
                print("| " + " | ".join(r) + " |")
        else:
            widths = [
                max(len(c), *(len(r[i]) for r in rows)) if rows else len(c)
                for i, c in enumerate(cols)
            ]
            print("  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=True)))
            for r in rows:
                print("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)))

    getter = img.dword(GAMECLIENT_VTABLE + GET_FRAME_SLOT)
    setter = img.dword(GAMECLIENT_VTABLE + SET_FRAME_SLOT)
    print(f"# Client-rate census - GameClient vtable 0x{GAMECLIENT_VTABLE:08X}")
    print(f"getFrame  = 0x{getter:08X}   setFrame = 0x{setter:08X}   field = GameClient+0x10")

    head("A. Readers of GameClient::getFrame()")
    sites = virtual_calls(img, THE_GAME_CLIENT, GET_FRAME_SLOT)
    rows, tally = [], defaultdict(int)
    for s in sites:
        verdict, why = classify(img, s)
        tally[verdict.split("(")[0]] += 1
        rows.append((f"0x{s:08X}", verdict, why[:64]))
    table(rows, ("site", "verdict", "evidence"))
    print(f"\n{len(sites)} sites: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))

    head("B. Readers of the rate block")
    rows = []
    for va, what in RATE_BLOCK.items():
        refs = img.refs(va)
        inits = static_inits(img, refs)
        live = len(refs) - inits
        rows.append(
            (
                f"0x{va:08X}",
                what,
                str(len(refs)),
                str(inits),
                str(live),
                " ".join(f"{r:08X}" for r in refs[:6]),
            )
        )
    table(rows, ("address", "constant", "refs", "static-init", "runtime", "sites (first 6)"))

    head("C. Rate constants living outside the block")
    rows = []
    for label, (value, distinctive) in SUSPECT_FLOATS.items():
        for va, refs in float_literals(img, value):
            if va in RATE_BLOCK:
                where = "block"
            else:
                where = "**MISSED**" if distinctive else "candidate"
            sites = " ".join(f"{r:08X}" for r in refs[:6])
            rows.append((f"0x{va:08X}", label, where, str(len(refs)), sites))
    table(rows, ("address", "value", "verdict", "refs", "sites (first 6)"))

    head("D. Readers of the sub-frame state")
    rows = []
    for field, what in ENGINE_FIELDS.items():
        if field == 0x34:
            reads = [
                va
                for lo, hi, _ in ENGINE_OWNERS
                for va in img.ordered
                if lo <= va <= hi
                and f"+ 0x{field:x}]" in img.insns[va][1]
                and img.insns[va][0] != "call"
            ]
            note = "confined to " + ", ".join(n for _, _, n in ENGINE_OWNERS)
        else:
            reads = field_reads(img, THE_GAME_ENGINE, field)
            note = "via a fresh load of TheGameEngine"
        sites = " ".join(f"{r:08X}" for r in reads[:9])
        rows.append((f"+0x{field:02X}", what, str(len(reads)), note, sites))
    table(rows, ("field", "meaning", "reads", "how reached", "sites (first 9)"))

    head("E. Client-frame-valued globals")
    rows = []
    for va, what in FRAME_GLOBALS.items():
        refs = img.refs(va)
        rows.append((f"0x{va:08X}", what, str(len(refs)), " ".join(f"{r:08X}" for r in refs[:8])))
    table(rows, ("global", "meaning", "refs", "sites (first 8)"))

    head("F. The pacing helpers")
    for target, what in (
        (SUBFRAME_PREDICATE, "sub-frame predicate"),
        (ALPHA_RECOMPUTE, "alpha recompute"),
        (TIMECODE_SINK, "timecode sink"),
    ):
        callers = img.callers(target)
        sites = " ".join(f"{c:08X}" for c in callers)
        print(f"0x{target:08X}  {what}: {len(callers)} callers - {sites}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    report(Image(args[0] if args else DEFAULT_PATH), "--md" in sys.argv)


if __name__ == "__main__":
    main()
