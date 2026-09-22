"""The perf-stage-readout patch: accumulate the render profile the engine already produces.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/perf-stage-readout.md``.

**What the engine already does.** Thirty times per drawn frame it constructs a `PerfScope` - a
stack object naming one stage of the render, `UpdateShadowMap` through `MeshFXShader` - and
destroys it when the stage ends. The constructor calls `D3DPERF_BeginEvent` through
`PERF_D3D_BEGIN_EVENT_PTR` and the destructor calls `D3DPERF_EndEvent`, so a PIX capture of this
game comes out labelled. Nothing else consumes those events: with no profiler attached the two
`d3d9.dll` entry points return immediately and the thirty scopes measure nothing.

**What this does.** Appends a ``.perfstg`` PE section holding a counter block and two short
routines, and hooks the scope class's constructor and destructor into them. Every scope entry
stamps `QueryPerformanceCounter` onto a nesting stack; every scope exit folds the elapsed ticks
into a per-site slot as **inclusive** time, subtracts what its children took to get **exclusive**
time, and adds its own total to its parent's child accumulator. The result is a live
inclusive/exclusive profile of the render, one row per call site, readable out of the running
process at the section's base address.

**Why the constructor and not the D3DPERF wrapper.** The name is `strncpy`'d into the object on
the constructor's fourth instruction, so by the time `PERF_BEGIN_EVENT` sees it the pointer is a
stack address - `[ebp-0x158]`, shared by every scope in the same function. Hooking the wrapper
would key four different stages to one slot.

**Why the call site and not the name.** The obvious key at the constructor is the name pointer,
and for twenty-six of the thirty sites it is an `.rdata` literal: stable, unique, one `cmp`. **The
other four build the name on the caller's stack.** The two `MeshDX8Render` sites and the two
`MeshFXShader` ones concatenate a per-mesh string into a stack buffer, push *that* as the name,
and pass the stage's literal as the **category** instead. Keyed on the name, those four claim a
slot per distinct stack address: measured live, they filled all sixty-four slots within seconds,
counted four million table-full misses, and the two per-mesh stages - the interesting ones - never
got a row at all.

So the key is the **return address** at ``[esp]``: the call site, which is in `.text`, is fixed for
the life of the process, is unique per site, and costs exactly what the name pointer cost. Thirty
sites means at most thirty keys. The name a site *prints* comes back from :data:`STAGE_SITES`,
which the reader owns and `apply` checks against the binary.

**Nothing is displaced on the exit side.** `PERF_SCOPE_DTOR` is five bytes and all five are a
`jmp` to `PERF_END_EVENT`, so the hook replaces a jump with a jump and the cave ends with the
jump that was there. The entry side displaces six bytes, `mov eax, [esp+4]` / `test eax, eax`, and
re-runs them at the end of its routine rather than the start - the `test` sets the flags the `je`
at `0x00517699` reads, and anything between would have to preserve them.

**It measures the scope, not the event.** The two D3DPERF pointers are untouched, so a PIX capture
still works and still says the same thing. What is added is an accumulator the engine never had.

**Cost.** Two `QueryPerformanceCounter` calls and about forty instructions per scope. Twenty-six of
the thirty scopes run once per frame; `MeshDX8Render` and `MeshFXShader` run per mesh, which on a
heavy frame is thousands. That is the honest cost of this patch and it is why it is a diagnostic
rather than something to ship - though note the engine is *already* paying two `strncpy`s and a
`strlen` per scope on that same path to build a name nothing reads, which is a larger per-mesh cost
than this adds and is scoped separately in the document.

**Client-local.** It reads no simulation state and writes none: the counters live in the new
section and nothing in the engine can see them. Peers need not agree on it, replays cross it, and
one player may profile a match everyone else plays on stock binaries. No INI change.

**Robustness.** The nesting stack is bounds-checked at both ends and the slot table is a
fixed-capacity open-addressed map, so an unbalanced scope or an unexpected thirty-first call site
costs a counter and never a write outside the section. The load screen draws on its own thread
(`multicore.md` §1.1) and can enter these scopes concurrently; the counters are not interlocked, so
numbers gathered while a map is loading may be mixed. That is a wrong number, not a wrong write.
"""

from __future__ import annotations

import struct

from ..addresses import (
    PERF_BEGIN_EVENT,
    PERF_BEGIN_EVENT_BYTES,
    PERF_END_EVENT,
    PERF_END_EVENT_BYTES,
    PERF_SCOPE_CTOR,
    PERF_SCOPE_CTOR_BYTES,
    PERF_SCOPE_CTOR_ENTRY,
    PERF_SCOPE_CTOR_RESUME,
    PERF_SCOPE_DTOR,
    PERF_SCOPE_DTOR_ENTRY,
    PERF_SCOPE_STAGE_SITE,
    PERF_SCOPE_STAGE_SITE_BYTES,
    QUERY_PERFORMANCE_COUNTER_IAT,
)
from ..asm import JAE, JBE, JE, JNZ, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "BLOCK_MAGIC",
    "BLOCK_VERSION",
    "CODE_OFFSET",
    "enter_va",
    "leave_va",
    "OFF_DEPTH",
    "OFF_OVERFLOW",
    "OFF_SCRATCH",
    "OFF_SLOTS",
    "OFF_SLOTS_USED",
    "OFF_STACK",
    "OFF_TABLE_FULL",
    "OFF_UNBALANCED",
    "SECTION_NAME",
    "SLOT_CAPACITY",
    "SLOT_SIZE",
    "STACK_CAPACITY",
    "STAGE_NAMES",
    "STAGE_SITES",
    "PerfStageReadoutPatch",
    "build_code",
]

SECTION_NAME = ".perfstg"  # 8 chars exactly: the PE name field is 8 bytes and truncates silently

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave is code *and*
# the counters it writes, so unlike a pure-gate cave this section has to be writable.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: ``'PSTG'`` little-endian, so a reader scanning the process for the block recognises it without
#: being told where the section landed.
BLOCK_MAGIC = 0x47545350
BLOCK_VERSION = 1

#: One slot per call site. The engine has 30, and the table is open-addressed on the return
#: address, so the capacity is a power of two well above that - a load factor under a half is what
#: keeps the probe short on the per-mesh scopes. The thirty sites average 1.3 probes.
SLOT_CAPACITY = 64
SLOT_SIZE = 24  # call site, calls, inclusive (u64), exclusive (u64)

#: How deep the scopes nest. Observed maximum is 3 (`RenderViews` -> `RenderTerrain` ->
#: `MeshDX8Render`); 32 is headroom, and exceeding it costs a counter rather than a write.
STACK_CAPACITY = 32
_FRAME_SIZE = 24  # slot pointer, pad, start tick (u64), child ticks (u64)

# --- the counter block, at the section's base VA -------------------------------------------
OFF_MAGIC = 0x00
OFF_VERSION = 0x04
OFF_SLOT_CAPACITY = 0x08
OFF_STACK_CAPACITY = 0x0C
OFF_DEPTH = 0x10
OFF_SLOTS_USED = 0x14
OFF_OVERFLOW = 0x18  # a scope entered past STACK_CAPACITY
OFF_UNBALANCED = 0x1C  # a scope left with the stack already empty
OFF_TABLE_FULL = 0x20  # a call site that found no free slot
OFF_RESERVED = 0x24
OFF_SCRATCH = 0x28  # where the exit's QueryPerformanceCounter lands
OFF_SLOTS = 0x30
OFF_STACK = OFF_SLOTS + SLOT_CAPACITY * SLOT_SIZE

#: Where the code begins, past the block. Fixed rather than computed so that the routines can
#: address their own counters with absolute operands while they are still being emitted.
CODE_OFFSET = OFF_STACK + STACK_CAPACITY * _FRAME_SIZE

# --- offsets within one slot and one stack frame --------------------------------------------
_SLOT_SITE = 0
_SLOT_CALLS = 4
_SLOT_INCLUSIVE = 8
_SLOT_EXCLUSIVE = 16
_FRAME_SLOT = 0
_FRAME_START = 8
_FRAME_CHILD = 16

#: **The table the reader labels its rows with**: the address each of the thirty call sites
#: returns to (its `call` VA plus five, which is what the cave sees at ``[esp]``), and the stage
#: that site stands for.
#:
#: Twenty-six sites push an `.rdata` literal as the scope's *name* and that literal is the label.
#: **Four do not.** The two `MeshDX8Render` sites (``0x005431E2``, ``0x00543321``) and the two
#: `MeshFXShader` ones (``0x00573D95``, ``0x00573E18``) build a per-mesh string on the caller's
#: stack, push *that* as the name, and pass the stage literal as the **category** instead - so
#: their label here is the category, which is the thing a profile wants on the row. It is also
#: the whole reason the cave keys on the call site: those four sites' name pointer is a stack
#: address that moves every call, and keying on it claimed a slot per call until the table was
#: full. See the module docstring.
#:
#: `apply` checks every address in this table really is the byte after a `call` to the
#: constructor, so a build that moved one of them is refused rather than mislabelled.
STAGE_SITES = {
    0x00449DE5: "UpdateShadowMap",
    0x00449E47: "UpdateWaterReflection",
    0x00449FBF: "RenderViews",
    0x0044A04E: "RenderUI",
    0x0046B101: "RenderTrees",
    0x0046B255: "RenderShrubs",
    0x0046B432: "RenderBuffs",
    0x00470FB0: "RenderWater",
    0x00471016: "RenderDecalShadows",
    0x00471611: "RenderVolumeShadows",
    0x00471660: "RenderStaticSortLists",
    0x004716D7: "RenderParticles",
    0x00471731: "RenderSmudges",
    0x004E292A: "DoTerrainSystems",
    0x004E2DD8: "RenderTerrain",
    0x004E2EDD: "RenderRoads",
    0x004E2F4A: "RenderFloors",
    0x004E2FE7: "RenderScorches",
    0x004E3013: "RenderTreeShadows",
    0x004E303F: "RenderTerrainParticles",
    0x004E30FE: "RenderTerrainTracks",
    0x004E3146: "RenderWaypoints",
    0x004E3286: "RenderOrders",
    0x004E32B9: "RenderBibs",
    0x004E32F7: "RenderProps",
    0x005431E7: "MeshDX8Render",  # per mesh; the name is built on the stack, this is the category
    0x00543326: "MeshDX8Render",  # likewise
    0x00573CB2: "RenderFXShaderBatch",
    0x00573D9A: "MeshFXShader",  # likewise
    0x00573E1D: "MeshFXShader",  # likewise
}

#: The thirty scopes the stock build constructs, in the order their call sites appear. Recorded
#: for the document and for the test that asserts the names are still there - the patch itself
#: never reads them, because it keys on the call site rather than on a known list.
STAGE_NAMES = (
    "UpdateShadowMap",
    "UpdateWaterReflection",
    "RenderViews",
    "RenderUI",
    "RenderTrees",
    "RenderShrubs",
    "RenderBuffs",
    "RenderWater",
    "RenderDecalShadows",
    "RenderVolumeShadows",
    "RenderStaticSortLists",
    "RenderParticles",
    "RenderSmudges",
    "DoTerrainSystems",
    "RenderTerrain",
    "RenderRoads",
    "RenderFloors",
    "RenderScorches",
    "RenderTreeShadows",
    "RenderTerrainParticles",
    "RenderTerrainTracks",
    "RenderWaypoints",
    "RenderOrders",
    "RenderBibs",
    "RenderProps",
    "MeshDX8Render",
    "MeshFXShader",
    "RenderFXShaderBatch",
)

#: What has to be true of the image before either hook means anything.
#:
#: `PERF_SCOPE_STAGE_SITE` is the load-bearing one: it is `UpdateShadowMap`'s whole call sequence,
#: and it is what entitles the entry routine to read the name off `[esp+4]`. `PERF_SCOPE_CTOR` and
#: `PERF_SCOPE_DTOR` say the two hooked routines are the ones being described, and `PERF_END_EVENT`
#: says the destructor's tail jump still lands on the `D3DPERF_EndEvent` thunk - which is where the
#: exit routine has to put it back. `PERF_BEGIN_EVENT` is checked but not hooked, because a build
#: whose begin wrapper differs is one whose scope class has been rebuilt.
ANCHORS = {
    PERF_SCOPE_CTOR: PERF_SCOPE_CTOR_BYTES,
    PERF_SCOPE_DTOR: PERF_SCOPE_DTOR_ENTRY,
    PERF_BEGIN_EVENT: PERF_BEGIN_EVENT_BYTES,
    PERF_END_EVENT: PERF_END_EVENT_BYTES,
    PERF_SCOPE_STAGE_SITE: PERF_SCOPE_STAGE_SITE_BYTES,
}


def _disp8(value: int) -> int:
    """A negative byte displacement as the byte an opcode carries."""
    return value & 0xFF


def _block() -> bytes:
    """The counter block's initial contents: the self-describing header, then zeroes."""
    block = bytearray(CODE_OFFSET)
    struct.pack_into(
        "<IIII", block, OFF_MAGIC, BLOCK_MAGIC, BLOCK_VERSION, SLOT_CAPACITY, STACK_CAPACITY
    )
    return bytes(block)


def _emit(base_va: int) -> Asm:
    """The whole section: the counter block, then the two routines that fill it.

    ``base_va`` is where the section will be mapped, which is what lets the routines address their
    own counters with absolute operands. Laying the block out *first*, at a fixed size, is what
    makes those operands computable before the code has been emitted.

    Returns the un-finished :class:`~sage_patch.asm.Asm` rather than bytes, so that the one caller
    that needs to know *where* a routine landed can ask the layout instead of counting.
    """
    depth = base_va + OFF_DEPTH
    slots = base_va + OFF_SLOTS
    stack = base_va + OFF_STACK
    scratch = base_va + OFF_SCRATCH

    a = Asm(base_va + CODE_OFFSET)

    # --- scope entry: reached from PERF_SCOPE_CTOR's first six bytes ------------------------
    #
    # esp is exactly the constructor's entry esp, so [esp] is still the return address - which is
    # the key, for the reason in the module docstring. Everything is saved and restored, because
    # this runs before the function it is hooked into has established anything and the engine
    # expects an untouched machine.
    a.label("enter")
    a.emit(0x9C)  # pushfd
    a.emit(0x60)  # pushad                    ; +36 bytes of saved state
    a.emit(0x8B, 0x74, 0x24, 0x24)  # mov esi, [esp+0x24]   ; the return address = the call site
    # The depth is raised whatever happens, including when the stack is full. The destructor runs
    # once per constructor and lowers it once per run, so a scope that declines to record still
    # has to occupy a level - otherwise its matching exit closes somebody else's frame and every
    # measurement from then on is attributed one level out.
    a.emit(0xA1, struct.pack("<I", depth))  # mov eax, [depth]
    a.emit(0xFF, 0x05, struct.pack("<I", depth))  # inc dword [depth]
    a.emit(0x83, 0xF8, STACK_CAPACITY)  # cmp eax, STACK_CAPACITY
    a.jcc(JAE, "too_deep")

    a.emit(0x6B, 0xF8, _FRAME_SIZE)  # imul edi, eax, 24
    a.emit(0x81, 0xC7, struct.pack("<I", stack))  # add edi, stack    ; the frame to open

    # Every scope has a call site, including one whose name is null - the constructor skips its
    # body then, but the scope still happened and still took time, and the destructor runs either
    # way. So there is no "no slot" arm here: the key is the caller, not the argument.
    a.call("slot_for_site")
    a.emit(0x89, 0x1F)  # mov [edi], ebx                    ; frame.slot, or 0 if the table is full
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x89, 0x47, _FRAME_CHILD)  # mov [edi+16], eax   ; frame.child = 0
    a.emit(0x89, 0x47, _FRAME_CHILD + 4)  # mov [edi+20], eax

    a.emit(0x8D, 0x47, _FRAME_START)  # lea eax, [edi+8]
    a.emit(0x50)  # push eax
    a.emit(0xFF, 0x15, struct.pack("<I", QUERY_PERFORMANCE_COUNTER_IAT))  # call [QPC]
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    a.jmp("enter_resume")

    a.label("too_deep")
    a.emit(0xFF, 0x05, struct.pack("<I", base_va + OFF_OVERFLOW))  # inc dword [overflow]
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd

    # The displaced instructions, run last so the flags the `je` at 0x00517699 reads are the ones
    # `test` just set rather than anything this routine did.
    a.label("enter_resume")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jmp_absolute(PERF_SCOPE_CTOR_RESUME)

    # --- the slot for a call site: open addressing on the return address ---------------------
    #
    # Thirty sites, so thirty keys at most, into sixty-four slots. Comparing the key is one
    # instruction where comparing a string would be a loop. Clobbers eax/ecx/edx/ebx and returns
    # the slot's address in ebx, or zero if the table is full.
    a.label("slot_for_site")
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.emit(0xC1, 0xE8, 0x02)  # shr eax, 2                  ; call sites are tens of bytes apart
    a.emit(0x83, 0xE0, SLOT_CAPACITY - 1)  # and eax, 63
    a.emit(0xB9, struct.pack("<I", SLOT_CAPACITY))  # mov ecx, 64   ; the probe budget
    a.label("probe")
    a.emit(0x6B, 0xD0, SLOT_SIZE)  # imul edx, eax, 24
    a.emit(0x81, 0xC2, struct.pack("<I", slots))  # add edx, slots
    a.emit(0x8B, 0x1A)  # mov ebx, [edx]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "claim")
    a.emit(0x3B, 0xDE)  # cmp ebx, esi
    a.jcc(JE, "hit")
    a.emit(0x40)  # inc eax
    a.emit(0x83, 0xE0, SLOT_CAPACITY - 1)  # and eax, 63
    a.emit(0x49)  # dec ecx
    a.jcc(JNZ, "probe")
    a.emit(0xFF, 0x05, struct.pack("<I", base_va + OFF_TABLE_FULL))  # inc dword [table_full]
    a.emit(0x33, 0xDB)  # xor ebx, ebx
    a.emit(0xC3)  # ret
    a.label("claim")
    a.emit(0x89, 0x32)  # mov [edx], esi
    a.emit(0xFF, 0x05, struct.pack("<I", base_va + OFF_SLOTS_USED))  # inc dword [slots_used]
    a.label("hit")
    a.emit(0x8B, 0xDA)  # mov ebx, edx
    a.emit(0xC3)  # ret

    # --- scope exit: reached from PERF_SCOPE_DTOR, which was one jump and stays one jump ----
    a.label("leave")
    a.emit(0x9C)  # pushfd
    a.emit(0x60)  # pushad
    a.emit(0xA1, struct.pack("<I", depth))  # mov eax, [depth]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "unbalanced")
    a.emit(0x48)  # dec eax
    a.emit(0xA3, struct.pack("<I", depth))  # mov [depth], eax
    # The mirror of the entry's overflow arm: a level above the stack's capacity has no frame
    # behind it, so it is unwound and not accounted for.
    a.emit(0x83, 0xF8, STACK_CAPACITY)  # cmp eax, STACK_CAPACITY
    a.jcc(JAE, "leave_done")
    a.emit(0x6B, 0xF8, _FRAME_SIZE)  # imul edi, eax, 24
    a.emit(0x81, 0xC7, struct.pack("<I", stack))  # add edi, stack   ; the frame being closed

    a.emit(0x68, struct.pack("<I", scratch))  # push scratch
    a.emit(0xFF, 0x15, struct.pack("<I", QUERY_PERFORMANCE_COUNTER_IAT))  # call [QPC]

    # edx:eax = now - frame.start, the inclusive span of the scope just closed.
    a.emit(0xA1, struct.pack("<I", scratch))  # mov eax, [scratch]
    a.emit(0x8B, 0x15, struct.pack("<I", scratch + 4))  # mov edx, [scratch+4]
    a.emit(0x2B, 0x47, _FRAME_START)  # sub eax, [edi+8]
    a.emit(0x1B, 0x57, _FRAME_START + 4)  # sbb edx, [edi+12]

    # The whole span counts against the parent, whose frame is the one immediately below. At the
    # bottom of the stack there is none, and nothing is charged.
    a.emit(0x81, 0xFF, struct.pack("<I", stack))  # cmp edi, stack
    a.jcc(JBE, "no_parent")
    parent_child = _disp8(_FRAME_CHILD - _FRAME_SIZE)  # the frame below's child accumulator
    a.emit(0x01, 0x47, parent_child)  # add [edi-8], eax
    a.emit(0x11, 0x57, _disp8(_FRAME_CHILD + 4 - _FRAME_SIZE))  # adc [edi-4], edx
    a.label("no_parent")

    a.emit(0x8B, 0x1F)  # mov ebx, [edi]                    ; frame.slot
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "leave_done")
    a.emit(0xFF, 0x43, _SLOT_CALLS)  # inc dword [ebx+4]
    a.emit(0x01, 0x43, _SLOT_INCLUSIVE)  # add [ebx+8], eax
    a.emit(0x11, 0x53, _SLOT_INCLUSIVE + 4)  # adc [ebx+12], edx
    a.emit(0x2B, 0x47, _FRAME_CHILD)  # sub eax, [edi+16]   ; exclusive = inclusive - children
    a.emit(0x1B, 0x57, _FRAME_CHILD + 4)  # sbb edx, [edi+20]
    a.emit(0x01, 0x43, _SLOT_EXCLUSIVE)  # add [ebx+16], eax
    a.emit(0x11, 0x53, _SLOT_EXCLUSIVE + 4)  # adc [ebx+20], edx

    a.label("leave_done")
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    a.jmp_absolute(PERF_END_EVENT)

    a.label("unbalanced")
    a.emit(0xFF, 0x05, struct.pack("<I", base_va + OFF_UNBALANCED))  # inc dword [unbalanced]
    a.emit(0x61)  # popad
    a.emit(0x9D)  # popfd
    a.jmp_absolute(PERF_END_EVENT)

    return a


def _check_sites(data: bytes | bytearray) -> None:
    """Every address in :data:`STAGE_SITES` is the byte after a `call` to the constructor.

    The cave keys on a return address, and the reader turns that key back into a stage name
    through a table written against this build. A site that moved would still be *measured* - it
    would simply claim a slot of its own - but it would be reported under the wrong name or under
    none, and a mislabelled profile is worse than a missing one. So the table is checked the same
    way the hooked bytes are.
    """
    for site, name in STAGE_SITES.items():
        call = site - 5
        off = va_to_offset(data, call)
        if off is None:
            raise ValueError(f"{name}'s call site {call:#010x} is not mapped")
        if data[off] != 0xE8:
            raise ValueError(f"{name}'s call site {call:#010x} is not a call")
        target = call + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != PERF_SCOPE_CTOR:
            raise ValueError(
                f"{name}'s call site {call:#010x} calls {target:#010x}, not the scope "
                f"constructor at {PERF_SCOPE_CTOR:#010x} - this build's render is not the one "
                "the stage table was written against"
            )


def build_code(base_va: int) -> bytes:
    """The whole section as it is written to the file: the counter block, then the code."""
    return _block() + _emit(base_va).finish()


def enter_va(section_va: int) -> int:
    """Where the entry routine sits, given the section's base. It is first in the code, so this
    is the one address the layout cannot move."""
    return _emit(section_va).label_va("enter")


def leave_va(section_va: int) -> int:
    """Where the exit routine sits. Read off the emitted layout rather than counted by hand,
    which is the whole reason :class:`~sage_patch.asm.Asm` carries labels."""
    return _emit(section_va).label_va("leave")


class PerfStageReadoutPatch(Patch):
    name = "perf-stage-readout"
    author = "officialNecro"
    description = (
        "Accumulate the per-stage render profile the engine already produces and nothing "
        "consumes: the thirty named PerfScope objects a drawn frame constructs get inclusive "
        "and exclusive timings in a .perfstg counter block, one row per call site, readable out "
        "of the running process. A diagnostic, not a speed-up - it costs "
        "two QueryPerformanceCounter calls per scope. Client-local. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        enter_off = va_to_offset(data, PERF_SCOPE_CTOR)
        leave_off = va_to_offset(data, PERF_SCOPE_DTOR)
        if enter_off is None or leave_off is None:
            raise ValueError(f"{PERF_SCOPE_CTOR:#010x} is not mapped - not the expected build")
        self._check_anchors(data)

        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        enter = enter_va(section_va)
        leave = leave_va(section_va)

        # Six bytes displaced, five of jump and one of nop: the cave re-runs both instructions.
        jump = b"\xe9" + struct.pack("<i", enter - (PERF_SCOPE_CTOR + 5)) + b"\x90"
        apply_byte_patch(
            data,
            enter_off,
            PERF_SCOPE_CTOR_ENTRY,
            jump,
            "PerfScope::PerfScope -> perf-stage-readout entry",
        )
        # The destructor was one jump to D3DPERF_EndEvent and stays one jump; the cave makes the
        # same jump at its end, so nothing is displaced here at all.
        apply_byte_patch(
            data,
            leave_off,
            PERF_SCOPE_DTOR_ENTRY,
            b"\xe9" + struct.pack("<i", leave - (PERF_SCOPE_DTOR + 5)),
            "PerfScope::~PerfScope -> perf-stage-readout exit",
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
                    "render-scope class is not the one the readout was written against"
                )
        _check_sites(data)

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located

        for va, label, expected in (
            (PERF_SCOPE_CTOR, "constructor", enter_va(section_va)),
            (PERF_SCOPE_DTOR, "destructor", leave_va(section_va)),
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
