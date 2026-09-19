"""The script trace: every script a running game fires, frame by frame, and breakpoints on them.

`executeScript` already announces each script whose actions it is about to run - to the debug
DLL's logger, which does nothing without the DLL. Redirecting those four calls through a cave
records `(frame, true/false, Script *, team member)` into a ring buffer and then carries on into
the logger, so the game behaves exactly as before. Scripts that fire their actions sequentially
never reach the logger; their condition test is wrapped instead, and a "yes" is recorded
(`sage_patch/docs/script-debugger.md` §2.1).

**Breakpoints** ride the same hooks. Every event is checked against a table of `Script *`s, each
with a mask of the event kinds it breaks on, whether or not recording is on. A hit stores what hit
and sets the frame gate (`script_debugger.FrameGate`) to held. The gate is only asked at the start
of the next dispatcher call, so the rest of the frame's scripts still run and the game stops on
the frame boundary - never between two actions.

The cave is written by the game and read by the controller:

    +0x00  'STRC'       the tag a later attach recognises the cave by
    +0x04  version
    +0x08  written      events ever written; slot = written % capacity
    +0x0C  capacity     a power of two
    +0x10  recording    0 stops recording without unhooking
    +0x14  gate         the address of the frame gate's mode, 0 for none
    +0x18  breakpoints  entries in use in the table
    +0x1C  hits         breakpoint hits ever
    +0x20  hit script, hit frame, hit kind - the last hit
    +0x40  code
    +0x200 the breakpoint table: `Script *`, kind mask; 64 of them
    +0x400 the ring: 16 bytes an event - frame, kind, Script *, object id

A reader that falls more than a ring behind loses the oldest events, and is told how many.

Recording writes nothing the game reads, so a controller that dies leaves a game that runs exactly
as before. A breakpoint that hits after it died holds the game only until the gate's lease runs
out.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum

from sage_live.backends.live_patch import (
    LivePatcher,
    LivePatchError,
    LiveProcess,
    allocation_base,
    call_bytes,
    call_target,
)
from sage_patch.addresses import (
    GAME_LOGIC_FRAME,
    GAME_LOGIC_GAME_MODE,
    NETWORK_GAME_MODES,
    OBJECT_ID,
    SCRIPT_DEBUG_RUN_SCRIPT_LOG,
    SCRIPT_ENGINE_CURRENT_OBJECT,
    SCRIPT_ENGINE_EVALUATE,
    SCRIPT_EXECUTE_LOG_CALLS,
    SCRIPT_SEQUENTIAL_EVALUATE_CALL,
    SCRIPT_SEQUENTIAL_EVALUATE_CALL_BYTES,
    THE_GAME_LOGIC,
)
from sage_patch.asm import JE, JNC, JNE, JNZ, JZ, Asm

__all__ = [
    "BREAKPOINT_LIMIT",
    "CAPACITY",
    "TRACE_MAGIC",
    "BreakpointHit",
    "EventKind",
    "ScriptTrace",
    "TraceEvent",
    "build_trace_cave",
    "kind_mask",
]

TRACE_MAGIC = b"STRC"
VERSION = 2
CAPACITY = 16384
EVENT_SIZE = 16
BREAKPOINT_LIMIT = 64
_WRITTEN = 0x08
_CAPACITY = 0x0C
_RECORDING = 0x10
_GATE = 0x14
_BREAKPOINTS = 0x18
_HITS = 0x1C
_HIT_SCRIPT = 0x20
_HIT_FRAME = 0x24
_HIT_KIND = 0x28
_CODE = 0x40
_TABLE = 0x200
_RING = 0x400
CAVE_SIZE = _RING + CAPACITY * EVENT_SIZE
# The frame gate's "held" mode, written by a breakpoint hit.
_GATE_HELD = 1


class EventKind(IntEnum):
    TRUE_ACTIONS = 1
    FALSE_ACTIONS = 2
    SEQUENTIAL = 3


@dataclass(frozen=True)
class TraceEvent:
    frame: int
    kind: EventKind
    script: int  # the `Script *`, which `LiveScript.address` names
    object_id: int  # the team member a team script ran for, 0 otherwise


@dataclass(frozen=True)
class BreakpointHit:
    count: int  # hits ever; a change is a new hit
    script: int
    frame: int
    kind: EventKind | None


def kind_mask(kinds: Iterable[EventKind]) -> int:
    """A breakpoint's mask: bit `kind` set for each kind it breaks on."""
    mask = 0
    for kind in kinds:
        mask |= 1 << kind
    return mask


def build_trace_cave(base: int) -> tuple[bytes, int, int]:
    """The cave for address `base`, and where its two entry points are: `(bytes, log, sequential)`.

    `log` replaces the logger calls: it records and then jumps on to the logger, so the stack the
    logger sees is the one `executeScript` built. `sequential` replaces the sequential path's
    condition test: it makes the same call, records a "yes", and returns what the test said.
    """
    head = TRACE_MAGIC + struct.pack("<IIIIIII", VERSION, 0, CAPACITY, 1, 0, 0, 0)
    head = head.ljust(_CODE, b"\x00")

    def at(offset: int) -> bytes:
        return struct.pack("<I", base + offset)

    a = Asm(base + _CODE)

    # One event. In: `ecx` the kind, `edx` the `Script *`, `eax` the object id. Clobbers `eax`,
    # `ecx`, `edx`; everything else is kept.
    a.label("record")
    a.call("breakpoints")
    a.emit(0x83, 0x3D, at(_RECORDING), 0x00)  # cmp dword [recording], 0
    a.jcc(JE, "record_done")
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x1D, at(_WRITTEN))  # mov ebx, [written]
    a.emit(0x8B, 0xF3)  # mov esi, ebx
    a.emit(0x81, 0xE6, struct.pack("<I", CAPACITY - 1))  # and esi, capacity - 1
    a.emit(0xC1, 0xE6, 0x04)  # shl esi, 4
    a.emit(0x81, 0xC6, at(_RING))  # add esi, ring
    a.emit(0x89, 0x4E, 0x04)  # mov [esi+4], ecx      ; kind
    a.emit(0x89, 0x56, 0x08)  # mov [esi+8], edx      ; Script *
    a.emit(0x89, 0x46, 0x0C)  # mov [esi+0xc], eax    ; object id
    a.call("frame")
    a.emit(0x89, 0x0E)  # mov [esi], ecx          ; frame
    # The slot is complete before the count moves past it, so a reader never sees half an event.
    a.emit(0x43)  # inc ebx
    a.emit(0x89, 0x1D, at(_WRITTEN))  # mov [written], ebx
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.label("record_done")
    a.emit(0xC3)  # ret

    # `ecx` = the logic frame, 0 without a game logic. Nothing else is touched.
    a.label("frame")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JZ, "frame_done")
    a.emit(0x8B, 0x49, GAME_LOGIC_FRAME)  # mov ecx, [ecx+0x40]
    a.label("frame_done")
    a.emit(0xC3)  # ret

    # Check the event in `ecx`/`edx` against the table; on a hit, note it and hold the gate.
    # Keeps every register.
    a.label("breakpoints")
    a.emit(0x83, 0x3D, at(_BREAKPOINTS), 0x00)  # cmp dword [breakpoints], 0
    a.jcc(JE, "bp_none")
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x1D, at(_BREAKPOINTS))  # mov ebx, [breakpoints]
    a.emit(0xBE, at(_TABLE))  # mov esi, table
    a.label("bp_loop")
    a.emit(0x39, 0x16)  # cmp [esi], edx
    a.jcc(JNE, "bp_next")
    a.emit(0x0F, 0xA3, 0x4E, 0x04)  # bt [esi+4], ecx       ; the kind's bit in the mask
    a.jcc(JNC, "bp_next")
    a.emit(0x89, 0x15, at(_HIT_SCRIPT))  # mov [hit script], edx
    a.emit(0x89, 0x0D, at(_HIT_KIND))  # mov [hit kind], ecx
    a.emit(0x51)  # push ecx
    a.call("frame")
    a.emit(0x89, 0x0D, at(_HIT_FRAME))  # mov [hit frame], ecx
    a.emit(0x59)  # pop ecx
    # The hit is complete before the count moves, as with a ring slot.
    a.emit(0xFF, 0x05, at(_HITS))  # inc dword [hits]
    a.emit(0x8B, 0x35, at(_GATE))  # mov esi, [gate]
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JZ, "bp_done")
    a.emit(0xC7, 0x06, struct.pack("<I", _GATE_HELD))  # mov dword [esi], 1
    a.jmp("bp_done")
    a.label("bp_next")
    a.emit(0x83, 0xC6, 0x08)  # add esi, 8
    a.emit(0x4B)  # dec ebx
    a.jcc(JNZ, "bp_loop")
    a.label("bp_done")
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.label("bp_none")
    a.emit(0xC3)  # ret

    # In place of `call logger` inside `executeScript`: [esp+8] is `isTrue`, `esi` the script,
    # `edi` TheScriptEngine. The logger is `cdecl` and reads only its stack arguments, so `eax`,
    # `ecx` and `edx` are free here.
    log = a.va
    a.emit(0x0F, 0xB6, 0x4C, 0x24, 0x08)  # movzx ecx, byte [esp+8]
    a.emit(0xF7, 0xD9)  # neg ecx
    a.emit(0x83, 0xC1, EventKind.FALSE_ACTIONS)  # add ecx, 2       ; true -> 1, false -> 2
    a.emit(0x8B, 0xD6)  # mov edx, esi
    a.emit(0x8B, 0x87, struct.pack("<I", SCRIPT_ENGINE_CURRENT_OBJECT))  # mov eax, [edi+obj]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "log_record")
    a.emit(0x8B, 0x40, OBJECT_ID)  # mov eax, [eax+0x74]
    a.label("log_record")
    a.call("record")
    a.jmp_absolute(SCRIPT_DEBUG_RUN_SCRIPT_LOG)

    # In place of the sequential path's `call evaluate(script, 0, 0)`: the same call on copies of
    # the three arguments, then a record when it said yes. `edi` is the script at that site.
    sequential = a.va
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]
    a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]
    a.call_absolute(SCRIPT_ENGINE_EVALUATE)  # ret 0xc takes the copies
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JZ, "sequential_done")
    a.emit(0x50)  # push eax
    a.emit(0xB9, struct.pack("<I", EventKind.SEQUENTIAL))  # mov ecx, 3
    a.emit(0x8B, 0xD7)  # mov edx, edi
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.call("record")
    a.emit(0x58)  # pop eax
    a.label("sequential_done")
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc
    code = a.finish()
    if _CODE + len(code) > _TABLE:
        raise AssertionError("the trace code outgrew its space")
    return head + code, log, sequential


class ScriptTrace:
    """Record the scripts a running game fires, break on chosen ones, and read it all back.

    `attach` installs the five hooks, or adopts the cave an earlier session left (replacing it when
    an older version laid it out); `close` takes them out. `read` returns what was recorded since
    the last call; `hit` is the last breakpoint hit.
    """

    def __init__(self, process: LiveProcess) -> None:
        self.process = process
        self.patcher = LivePatcher(process)
        self.cave: int | None = None
        self.adopted = False
        self._read = 0
        self.dropped = 0

    def __enter__(self) -> ScriptTrace:
        self.attach()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _u32(self, address: int) -> int | None:
        raw = self.process.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def _sites(self) -> list[tuple[int, bytes, bool]]:
        """`(site, stock bytes, is the sequential site)` for every hook."""
        sites = [(site, stock, False) for site, stock in SCRIPT_EXECUTE_LOG_CALLS.items()]
        sites.append((SCRIPT_SEQUENTIAL_EVALUATE_CALL, SCRIPT_SEQUENTIAL_EVALUATE_CALL_BYTES, True))
        return sites

    def _existing_cave(self) -> int | None:
        """The head of the cave an earlier session's hooks lead to, if the first site holds one."""
        site, stock, _ = self._sites()[0]
        current = self.process.read(site, 5)
        if current is None or current == stock:
            return None
        target = call_target(site, current)
        if target is None:
            return None
        base = allocation_base(target)
        return base if self.process.read(base, len(TRACE_MAGIC)) == TRACE_MAGIC else None

    def _retire(self, base: int) -> None:
        """Take out the hooks of a cave another version laid out, so this one can replace it."""
        old = LivePatcher(self.process)
        old.adopt(base)
        for site, stock, _ in self._sites():
            current = self.process.read(site, 5)
            if current is not None and current != stock:
                target = call_target(site, current)
                if target is not None and allocation_base(target) == base:
                    old.hook(site, stock, current)
        notes = old.close()
        if notes:
            raise LivePatchError("an older trace could not be removed: " + "; ".join(notes))

    def attach(self, allow_network: bool = False, recording: bool = True) -> None:
        logic = self._u32(THE_GAME_LOGIC)
        mode = self._u32(logic + GAME_LOGIC_GAME_MODE) if logic else None
        if mode in NETWORK_GAME_MODES and not allow_network:
            raise LivePatchError(
                f"this is a network game (mode {mode}); a trace hook is refused there"
            )
        base = self._existing_cave()
        if base is not None and self._u32(base + 4) != VERSION:
            self._retire(base)
            base = None
        if base is not None:
            self.adopted = True
            self.patcher.adopt(base)
        else:
            base = self.patcher.allocate(CAVE_SIZE)
            image, _, _ = build_trace_cave(base)
            if not self.process.write(base, image):
                raise LivePatchError("writing the trace cave failed")
        _, log, sequential = build_trace_cave(base)
        self.cave = base
        try:
            for site, stock, is_sequential in self._sites():
                target = sequential if is_sequential else log
                self.patcher.hook(site, stock, call_bytes(site, target))
        except LivePatchError:
            self.patcher.close(free_caves=not self.adopted)
            self.cave = None
            raise
        self.set_recording(recording)
        self._read = self._u32(base + _WRITTEN) or 0

    def _set(self, offset: int, value: int) -> None:
        if self.cave is None:
            raise LivePatchError("not attached")
        if not self.process.write(self.cave + offset, struct.pack("<I", value)):
            raise LivePatchError(f"writing the trace control block at +0x{offset:X} failed")

    def set_recording(self, recording: bool) -> None:
        self._set(_RECORDING, int(recording))

    @property
    def recording(self) -> bool:
        return self.cave is not None and bool(self._u32(self.cave + _RECORDING))

    def set_gate(self, mode_address: int | None) -> None:
        """Where a hit writes "held": a `FrameGate`'s mode field, or nowhere."""
        self._set(_GATE, mode_address or 0)

    def set_breakpoints(self, breakpoints: dict[int, int]) -> None:
        """Replace the table with `{Script *: kind mask}`.

        The count goes to zero first and up last, so the game never checks a half-written table.
        """
        if len(breakpoints) > BREAKPOINT_LIMIT:
            raise LivePatchError(f"at most {BREAKPOINT_LIMIT} breakpoints")
        if self.cave is None:
            raise LivePatchError("not attached")
        self._set(_BREAKPOINTS, 0)
        table = b"".join(struct.pack("<II", s, m) for s, m in sorted(breakpoints.items()))
        if table and not self.process.write(self.cave + _TABLE, table):
            raise LivePatchError("writing the breakpoint table failed")
        self._set(_BREAKPOINTS, len(breakpoints))

    def hit(self) -> BreakpointHit | None:
        """The last breakpoint hit, or None before the first."""
        if self.cave is None:
            return None
        raw = self.process.read(self.cave + _HITS, 0x10)
        if raw is None:
            return None
        count, script, frame, kind = struct.unpack("<IIII", raw)
        if not count:
            return None
        known = kind in EventKind._value2member_map_
        return BreakpointHit(count, script, frame, EventKind(kind) if known else None)

    def read(self) -> list[TraceEvent]:
        """Every event recorded since the last read, oldest first."""
        if self.cave is None:
            raise LivePatchError("not attached")
        written = self._u32(self.cave + _WRITTEN)
        if written is None:
            raise LivePatchError("the trace ring is unreadable - the game exited?")
        if written < self._read:
            # The counter is 32-bit and a new session may have reset it; start again from here.
            self._read = written
        pending = written - self._read
        if pending > CAPACITY:
            self.dropped += pending - CAPACITY
            self._read = written - CAPACITY
            pending = CAPACITY
        events: list[TraceEvent] = []
        first = self._read % CAPACITY
        # At most two reads: up to the end of the ring, then from its start.
        spans = [(first, min(pending, CAPACITY - first)), (0, pending - (CAPACITY - first))]
        for start, count in spans:
            if count <= 0:
                continue
            raw = self.process.read(self.cave + _RING + start * EVENT_SIZE, count * EVENT_SIZE)
            if raw is None:
                raise LivePatchError("reading the trace ring failed")
            for frame, kind, script, object_id in struct.iter_unpack("<IIII", raw):
                if kind in EventKind._value2member_map_:
                    events.append(TraceEvent(frame, EventKind(kind), script, object_id))
        self._read = written
        return events

    def close(self) -> list[str]:
        """Take the hooks out. The cave stays only if a hook could not be restored."""
        if self.cave is not None:
            for offset in (_BREAKPOINTS, _GATE, _RECORDING):
                try:
                    self._set(offset, 0)
                except LivePatchError:
                    break
        notes = self.patcher.close()
        self.cave = None
        return notes
