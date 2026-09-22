"""The perf-scope-skip patch: stop building PIX event names nobody is listening for.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/perf-scope-skip.md``; the render-scope class itself is derived in
``../docs/perf-stage-readout.md``, whose §6 is this patch's scoping note.

**The defect.** The engine wraps its render in thirty named `PerfScope` objects, each of which
opens a PIX event. Building the name is not free:

```
strncpy(this, name, 0x100);          ; strncpy PADS to n - 256 bytes, always
memcpy(this + 0x100, "SceneAnalyst", 13);
len = strlen(this + 0x100);
strncpy(this + 0x100 + len, category, 0x40 - len);
```

- roughly **333 bytes written per scope**, and then a widening loop copies the result into a second
  buffer as UTF-16 before `D3DPERF_BeginEvent` is called with it.

Two of the thirty scopes - `MeshDX8Render` and `MeshFXShader` - are **per mesh**, so a frame
drawing three thousand meshes does this about six thousand times: on the order of a megabyte of
string traffic, inside the render path, every frame. And with no profiler attached
`D3DPERF_BeginEvent` returns immediately without reading a byte of it. **The whole thing is built
for a reader that is not there.**

**What this does.** Appends a ``.pscope`` PE section and hooks two places.

- At `PERF_SCOPE_NULL_GATE` - the constructor's own `je` to its "this scope has no name, do
  nothing" exit - a four-instruction gate sends the scope down that same exit when nothing is
  listening. The engine's exit, not a new one: it already returns the object in `eax` and unwinds
  the one `push esi` the entry made, which is exactly the ABI a skipped scope needs.
- At `D3DPERF_SETOPTIONS_STORE` - the tail of the engine's own D3DPERF resolve, where `d3d9.dll` is
  loaded and its handle is in hand - a probe asks **`D3DPERF_GetStatus`**, which the engine never
  resolves, whether a profiler is attached, and records the answer in one byte.

So a PIX capture still works and still comes out labelled; every other run stops building the
labels. The byte defaults to **skip**, which is also what a run with no device gets.

**Why `D3DPERF_GetStatus` and not the pointer the engine already has.** The obvious test is whether
`0x00DD361C` is null, and it never is: `d3d9.dll` exports `D3DPERF_BeginEvent` whether or not
anyone is listening, so the engine's own null test can never fire. `GetStatus` is the documented
question and the only one that distinguishes the two cases. If it cannot be resolved - a d3d9
replacement that omits it, DXVK - the probe records "not listening", which is the fast path and the
correct answer for a runtime with no PIX in it.

**What is left behind.** The destructor still calls `D3DPERF_EndEvent` on a scope whose
`BeginEvent` never happened. An unbalanced `End` matters only to a profiler's nesting counter, and
**when a profiler is attached this gate does not fire** - so the only runs that produce the
imbalance are the ones with nothing there to mind it, where `D3DPERF_EndEvent` returns immediately
without touching anything. (The constructor is *written* to tolerate a null name and the destructor
is unconditional, so the engine's own code anticipates this shape - but no call site passes null,
so that arm is dead in a stock build and is not evidence of anything.) What is
left is one predictable indirect call against the ~313 bytes and two CRT calls this removes, and
gating it too would mean editing bytes :mod:`~sage_patch.patches.perf_stage_readout` owns.

**Nothing reads the buffer.** Every reference to a scope object's stack slot, in all eight
functions that construct one, is a `lea ecx` feeding the constructor or the destructor - 64 of
them, no reads. And the constructor uses `ebp` as a saved scratch register rather than as a frame
pointer, so neither it nor the five-byte destructor can touch the caller's `[ebp-4]` unwind state.
Skipping the body is invisible to everything but the profiler that is not attached.

**Composition.** Order-independent with :mod:`~sage_patch.patches.perf_stage_readout`, which is the
pairing that matters: that patch hooks the constructor's **first six bytes** and the destructor,
this one hooks the `je` nine bytes in and a site in the D3D init, and neither reads bytes the other
writes. Applied together, the readout still times every scope and the scope no longer builds a
name - which is the combination worth running, because it measures what the render costs without
the measurement paying for a string.

**Client-local.** No simulation state, no INI surface, no replay or network effect.
"""

from __future__ import annotations

import struct

from ..addresses import (
    D3DPERF_MODULE_HANDLE,
    D3DPERF_RESOLVE_ANCHOR,
    D3DPERF_RESOLVE_ANCHOR_BYTES,
    D3DPERF_SET_OPTIONS_PTR,
    D3DPERF_SETOPTIONS_STORE,
    D3DPERF_SETOPTIONS_STORE_ENTRY,
    D3DPERF_SETOPTIONS_STORE_RESUME,
    GET_PROC_ADDRESS_IAT,
    PERF_SCOPE_CTOR_OBJECT_SETUP,
    PERF_SCOPE_CTOR_OBJECT_SETUP_BYTES,
    PERF_SCOPE_NULL_EXIT,
    PERF_SCOPE_NULL_EXIT_BYTES,
    PERF_SCOPE_NULL_GATE,
    PERF_SCOPE_NULL_GATE_ENTRY,
    PERF_SCOPE_NULL_GATE_RESUME,
    PERF_SCOPE_NULL_GATE_RESUME_BYTES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "BLOCK_MAGIC",
    "CODE_OFFSET",
    "GETSTATUS_NAME",
    "OFF_ENABLED",
    "OFF_PROBED",
    "SECTION_NAME",
    "PerfScopeSkipPatch",
    "build_code",
    "gate_va",
    "probe_va",
]

SECTION_NAME = ".pscope"

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE - the cave is code plus the
# one byte the probe writes and the gate reads.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: ``'PSSK'``, so the block is recognisable in a process without being told where it landed.
BLOCK_MAGIC = 0x4B535350

#: The export the engine never resolves. Carried as a literal here because there is no copy of this
#: string anywhere in `game.dat` - the engine resolves four D3DPERF entry points and this is a
#: fifth.
GETSTATUS_NAME = b"D3DPERF_GetStatus\x00"

OFF_MAGIC = 0x00
#: 0 = build no names, 1 = a profiler answered `D3DPERF_GetStatus`. **Default 0**, which is also
#: the right answer before the device exists.
OFF_ENABLED = 0x04
#: 1 once the probe has run at all, so a live reader can tell "no profiler" from "never asked".
OFF_PROBED = 0x05
OFF_NAME = 0x08
#: Where the code starts. Fixed, so both routines can address the flag byte absolutely while they
#: are still being emitted.
CODE_OFFSET = 0x20

#: What has to be true before either hook means anything.
#:
#: `PERF_SCOPE_CTOR_OBJECT_SETUP` is the constructor's `push esi` / `mov esi, ecx`. It is both what
#: the skip path's `pop esi` balances against and the first part of the constructor that
#: `perf-stage-readout`'s six-byte hook leaves alone, so it holds whichever patch was applied
#: first.
#:
#: `PERF_SCOPE_NULL_GATE` is the branch being replaced; `PERF_SCOPE_NULL_EXIT` is where it went,
#: which is the exit this patch reuses and the reason it needs no return sequence of its own; and
#: `PERF_SCOPE_NULL_GATE_RESUME` is the body the gate lets a live scope fall through to.
#:
#: `D3DPERF_RESOLVE_ANCHOR` is the whole resolve tail: the module handle the probe borrows, the
#: store it displaces, and the call it resumes into.
ANCHORS = {
    PERF_SCOPE_CTOR_OBJECT_SETUP: PERF_SCOPE_CTOR_OBJECT_SETUP_BYTES,
    PERF_SCOPE_NULL_GATE: PERF_SCOPE_NULL_GATE_ENTRY,
    PERF_SCOPE_NULL_GATE_RESUME: PERF_SCOPE_NULL_GATE_RESUME_BYTES,
    PERF_SCOPE_NULL_EXIT: PERF_SCOPE_NULL_EXIT_BYTES,
    D3DPERF_RESOLVE_ANCHOR: D3DPERF_RESOLVE_ANCHOR_BYTES,
}


def _block() -> bytes:
    block = bytearray(CODE_OFFSET)
    struct.pack_into("<I", block, OFF_MAGIC, BLOCK_MAGIC)
    block[OFF_NAME : OFF_NAME + len(GETSTATUS_NAME)] = GETSTATUS_NAME
    return bytes(block)


def _emit(base_va: int) -> Asm:
    """Both routines, laid out after the block so they can address its flag byte absolutely."""
    enabled = base_va + OFF_ENABLED
    probed = base_va + OFF_PROBED
    name = base_va + OFF_NAME

    a = Asm(base_va + CODE_OFFSET)

    # --- the gate: reached from the constructor's own `je`, with its flags intact ----------
    #
    # Nothing here may disturb `eax` (the name) or `esi` (the object): the body reaches the hook
    # with both live and pushes them at `0x005176AC`/`0x005176AD`. A `cmp` against memory and two
    # branches touch neither.
    a.label("gate")
    a.jcc(JE, "take_exit")  # the branch being replaced: a null name still does nothing
    a.emit(0x80, 0x3D, struct.pack("<I", enabled), 0x00)  # cmp byte [enabled], 0
    a.jcc(JNE, "run_body")  # somebody is listening -> build the name as stock

    a.label("take_exit")
    a.jmp_absolute(PERF_SCOPE_NULL_EXIT)  # the engine's own do-nothing exit
    a.label("run_body")
    a.jmp_absolute(PERF_SCOPE_NULL_GATE_RESUME)

    # --- the probe: one question, once, at the tail of the engine's D3DPERF resolve --------
    a.label("probe")
    a.emit(0xA3, struct.pack("<I", D3DPERF_SET_OPTIONS_PTR))  # the displaced store
    a.emit(0x60)  # pushad
    a.emit(0x9C)  # pushfd

    a.emit(0x68, struct.pack("<I", name))  # push "D3DPERF_GetStatus"
    a.emit(0xFF, 0x35, struct.pack("<I", D3DPERF_MODULE_HANDLE))  # push dword [d3d9 handle]
    a.emit(0xFF, 0x15, struct.pack("<I", GET_PROC_ADDRESS_IAT))  # call [GetProcAddress]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "not_listening")  # a d3d9 without it: take the fast path
    a.emit(0xFF, 0xD0)  # call eax        ; DWORD WINAPI D3DPERF_GetStatus(void)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "not_listening")
    a.emit(0xC6, 0x05, struct.pack("<I", enabled), 0x01)  # mov byte [enabled], 1
    a.jmp("probe_done")

    a.label("not_listening")
    a.emit(0xC6, 0x05, struct.pack("<I", enabled), 0x00)  # mov byte [enabled], 0

    a.label("probe_done")
    a.emit(0xC6, 0x05, struct.pack("<I", probed), 0x01)  # mov byte [probed], 1
    a.emit(0x9D)  # popfd
    a.emit(0x61)  # popad
    a.jmp_absolute(D3DPERF_SETOPTIONS_STORE_RESUME)
    return a


def build_code(base_va: int) -> bytes:
    """The whole section as it is written to the file: the flag block, then the two routines."""
    return _block() + _emit(base_va).finish()


def gate_va(section_va: int) -> int:
    return _emit(section_va).label_va("gate")


def probe_va(section_va: int) -> int:
    return _emit(section_va).label_va("probe")


class PerfScopeSkipPatch(Patch):
    name = "perf-scope-skip"
    author = "officialNecro"
    description = (
        "Stop the render-scope class building PIX event names when no profiler is listening. "
        "Each of the thirty named scopes a drawn frame opens spends two strncpy calls, a strlen "
        "and about 333 bytes building a string for a D3DPERF_BeginEvent that returns without "
        "reading it - and two of the thirty run per mesh. The patch asks D3DPERF_GetStatus once "
        "at device init and sends the scope down the engine's own do-nothing exit when the answer "
        "is no, so a PIX capture still works and every other run stops paying. Client-local. "
        "No INI change"
    )

    def apply(self, data: bytearray) -> None:
        gate_off = va_to_offset(data, PERF_SCOPE_NULL_GATE)
        probe_off = va_to_offset(data, D3DPERF_SETOPTIONS_STORE)
        if gate_off is None or probe_off is None:
            raise ValueError(f"{PERF_SCOPE_NULL_GATE:#010x} is not mapped - not the expected build")
        self._check_anchors(data)

        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)

        # Six bytes of `jcc rel32` become five of `jmp rel32` and a `nop`.
        gate = gate_va(section_va)
        apply_byte_patch(
            data,
            gate_off,
            PERF_SCOPE_NULL_GATE_ENTRY,
            b"\xe9" + struct.pack("<i", gate - (PERF_SCOPE_NULL_GATE + 5)) + b"\x90",
            "PerfScope::PerfScope null gate -> perf-scope-skip gate",
        )
        # Five bytes of store become five of jump; the cave re-runs the store first.
        probe = probe_va(section_va)
        apply_byte_patch(
            data,
            probe_off,
            D3DPERF_SETOPTIONS_STORE_ENTRY,
            b"\xe9" + struct.pack("<i", probe - (D3DPERF_SETOPTIONS_STORE + 5)),
            "D3DPERF resolve -> perf-scope-skip probe",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this build's "
                    "render-scope class or D3DPERF resolve is not the one this was written against"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located

        for va, label, expected in (
            (PERF_SCOPE_NULL_GATE, "gate", gate_va(section_va)),
            (D3DPERF_SETOPTIONS_STORE, "probe", probe_va(section_va)),
        ):
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{va:#010x} is not mapped by any section")
                continue
            if data[off] != 0xE9:
                problems.append(f"the {label} hook at {va:#010x} is not a jmp")
                continue
            target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != expected:
                problems.append(
                    f"the {label} hook jumps to {target:#010x}, expected {expected:#010x}"
                )

        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} section does not hold the expected block")
        return problems
