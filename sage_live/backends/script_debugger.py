"""The script debugger's frame gate: pause a running game's simulation, step it frame by frame, and
run a script's conditions or actions on demand.

The engine already has the mechanism. Its frame dispatcher runs the client phase - rendering,
camera, input, audio - and then asks one predicate whether the logic phase may run; a "no" holds
the simulation on the current frame while everything the player sees keeps going. The predicate
normally answers for `DebugWindowLite.dll`. This redirects the dispatcher's call to a small cave
that answers for us instead, so no DLL, no debug window and no command-line flag are involved,
and it attaches to a game that is already running (`sage_patch/docs/script-debugger.md` §1).

The same call is the game's own thread, once a frame, between two logic ticks, paused or not - so
it is also where a **command** runs: evaluate a script's conditions, or run its true or false
actions, with that script's player put in scope exactly as the engine's per-frame driver does it
(§4). The controller fills the command and moves `request`; the cave runs it on its next call and
moves `done` to match.

The cave reads a control block at its own head:

    +0x00  'SDBG'     the tag a later attach recognises the cave by
    +0x04  version
    +0x08  mode       0 run (defer to the engine), 1 paused, 2 run until `target`
    +0x0C  target     the logic frame mode 2 stops at
    +0x10  lease      client frames the controller has vouched for
    +0x14  hits       how many times the dispatcher has asked, for liveness
    +0x18  request    commands asked for; the cave runs one when this differs from `done`
    +0x1C  done       commands run
    +0x20  command    1 evaluate, 2 run the true actions, 3 run the false actions
    +0x24  script     the `Script *`
    +0x28  side       whose scope it runs in: a side index, which is also its player's index
    +0x2C  name       the script's name `AsciiString *`, as the engine passes it
    +0x30  result     the evaluation (0 / 1), 1 for actions run, -1 for a side with no player
    +0x40  the scope guard's 12 bytes
    +0x60  code

**The lease is what keeps a crash from freezing someone's match.** Every client frame spent paused
or stepping spends one; at zero the cave drops back to mode 0 by itself. The controller renews it
while it is alive, so a killed Python process leaves a game that resumes a few seconds later
rather than one frozen until it is closed.

Stepping is exact: mode 2 lets frames run until `GameLogic::m_frame` reaches the target and
switches itself back to paused inside the same dispatcher call, however slowly the controller
polls.
"""

from __future__ import annotations

import struct
import threading
import time
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
    FRAME_DISPATCHER_PAUSE_CALL,
    FRAME_DISPATCHER_PAUSE_CALL_BYTES,
    GAME_LOGIC_FRAME,
    GAME_LOGIC_GAME_MODE,
    NAME_KEY_TO_NAME,
    NETWORK_GAME_MODES,
    PLAYER_LIST_GET_NTH,
    PLAYER_NAME_KEY,
    SCRIPT_DEBUG_PAUSED,
    SCRIPT_ENGINE_CURRENT_OBJECT,
    SCRIPT_ENGINE_CURRENT_PLAYER,
    SCRIPT_ENGINE_EVALUATE,
    SCRIPT_ENGINE_RUN_ACTIONS,
    SCRIPT_ENGINE_SCOPE,
    SCRIPT_FALSE_ACTIONS,
    SCRIPT_SCOPE_ENTER,
    SCRIPT_SCOPE_LEAVE,
    SCRIPT_TRUE_ACTIONS,
    THE_GAME_LOGIC,
    THE_NAME_KEY_GENERATOR,
    THE_PLAYER_LIST,
)
from sage_patch.asm import JB, JE, JNE, JZ, Asm

__all__ = [
    "CAVE_SIZE",
    "CODE_OFFSET",
    "MAGIC",
    "Command",
    "FrameGate",
    "GateState",
    "Mode",
    "NetworkGameRefused",
    "build_gate_cave",
]

MAGIC = b"SDBG"
VERSION = 2
CODE_OFFSET = 0x60
CAVE_SIZE = 0x400

_MODE = 0x08
_TARGET = 0x0C
_LEASE = 0x10
_HITS = 0x14
_REQUEST = 0x18
_DONE = 0x1C
_COMMAND = 0x20
_SCRIPT = 0x24
_SIDE = 0x28
_NAME = 0x2C
_RESULT = 0x30
_GUARD = 0x40

# At 30 client frames a second, about fifteen seconds of grace.
DEFAULT_LEASE = 450
# A side with no player, which the cave reports instead of running anything.
NO_PLAYER = 0xFFFFFFFF


class Mode:
    RUN = 0
    PAUSED = 1
    RUN_UNTIL = 2


class Command(IntEnum):
    EVALUATE = 1
    RUN_TRUE_ACTIONS = 2
    RUN_FALSE_ACTIONS = 3


class NetworkGameRefused(LivePatchError):
    """Pausing one peer of a network game stalls or drops it for everyone."""


def build_gate_cave(base: int) -> bytes:
    """The control block and the predicate replacement, laid out for address `base`."""
    head = MAGIC + struct.pack("<IIIII", VERSION, Mode.RUN, 0, 0, 0)
    head = head.ljust(CODE_OFFSET, b"\x00")

    def at(offset: int) -> bytes:
        return struct.pack("<I", base + offset)

    def u32(value: int) -> bytes:
        return struct.pack("<I", value)

    a = Asm(base + CODE_OFFSET)
    # Called in place of the engine's predicate: `thiscall` on TheScriptEngine, no arguments,
    # plain `ret`, answer in `al`. Only `eax` and the flags are touched, a subset of what the
    # original clobbers; a command saves everything it uses.
    a.emit(0xA1, at(_REQUEST))  # mov eax, [request]
    a.emit(0x3B, 0x05, at(_DONE))  # cmp eax, [done]
    a.jcc(JE, "gate")
    a.call("command")
    a.label("gate")
    a.emit(0xFF, 0x05, at(_HITS))  # inc dword [hits]
    a.emit(0xA1, at(_MODE))  # mov eax, [mode]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "engine")
    a.emit(0x83, 0x3D, at(_LEASE), 0x00)  # cmp dword [lease], 0
    a.jcc(JE, "expired")
    a.emit(0xFF, 0x0D, at(_LEASE))  # dec dword [lease]
    a.emit(0x83, 0xF8, Mode.PAUSED)  # cmp eax, 1
    a.jcc(JE, "hold")
    a.emit(0xA1, u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "run")
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]
    a.emit(0x3B, 0x05, at(_TARGET))  # cmp eax, [target]
    a.jcc(JB, "run")
    a.emit(0xC7, 0x05, at(_MODE), u32(Mode.PAUSED))  # mov dword [mode], 1
    a.label("hold")
    a.emit(0xB0, 0x01)  # mov al, 1
    a.emit(0xC3)  # ret
    a.label("run")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0xC3)  # ret
    a.label("expired")
    a.emit(0xC7, 0x05, at(_MODE), u32(Mode.RUN))  # mov dword [mode], 0
    a.label("engine")
    # Mode 0 defers to the engine's own predicate, so a real debug DLL still works.
    a.jmp_absolute(SCRIPT_DEBUG_PAUSED)

    # One command, in the scope of its side's player - what the per-frame driver sets up around
    # each player's scripts: the current player, no current object, and the scope string.
    a.label("command")
    a.emit(0x60)  # pushad
    a.emit(0x8B, 0xF1)  # mov esi, ecx              ; TheScriptEngine
    a.emit(0xFF, 0xB6, u32(SCRIPT_ENGINE_CURRENT_PLAYER))  # push dword [esi+player]
    a.emit(0xFF, 0xB6, u32(SCRIPT_ENGINE_CURRENT_OBJECT))  # push dword [esi+object]
    a.emit(0x83, 0xA6, u32(SCRIPT_ENGINE_CURRENT_OBJECT), 0x00)  # and dword [esi+object], 0
    a.emit(0xFF, 0x35, at(_SIDE))  # push dword [side]
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.call_absolute(PLAYER_LIST_GET_NTH)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "no_player")
    a.emit(0x89, 0x86, u32(SCRIPT_ENGINE_CURRENT_PLAYER))  # mov [esi+player], eax
    a.emit(0xFF, 0x70, PLAYER_NAME_KEY)  # push dword [eax+0x50]
    a.emit(0x8B, 0x0D, u32(THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
    a.call_absolute(NAME_KEY_TO_NAME)  # ret 4; eax = AsciiString *
    a.emit(0x50)  # push eax                  ; value
    a.emit(0x8D, 0x86, u32(SCRIPT_ENGINE_SCOPE))  # lea eax, [esi+scope]
    a.emit(0x50)  # push eax                  ; target
    a.emit(0xB9, at(_GUARD))  # mov ecx, guard
    a.call_absolute(SCRIPT_SCOPE_ENTER)  # ret 8
    a.emit(0x8B, 0x3D, at(_SCRIPT))  # mov edi, [script]
    a.emit(0xA1, at(_COMMAND))  # mov eax, [command]
    a.emit(0x83, 0xF8, Command.EVALUATE)  # cmp eax, 1
    a.jcc(JNE, "actions")
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(SCRIPT_ENGINE_EVALUATE)  # ret 0xc
    a.emit(0x0F, 0xB6, 0xC0)  # movzx eax, al
    a.emit(0xA3, at(_RESULT))  # mov [result], eax
    a.jmp("leave")
    a.label("actions")
    a.emit(0x8B, 0x5F, SCRIPT_TRUE_ACTIONS)  # mov ebx, [edi+0x34]
    a.emit(0x83, 0xF8, Command.RUN_FALSE_ACTIONS)  # cmp eax, 3
    a.jcc(JNE, "actions_run")
    a.emit(0x8B, 0x5F, SCRIPT_FALSE_ACTIONS)  # mov ebx, [edi+0x38]
    a.label("actions_run")
    a.emit(0xC7, 0x05, at(_RESULT), u32(0))  # mov dword [result], 0
    a.emit(0x85, 0xDB)  # test ebx, ebx          ; an empty list runs nothing
    a.jcc(JZ, "leave")
    a.emit(0xFF, 0x35, at(_NAME))  # push dword [name]
    a.emit(0x57)  # push edi
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(SCRIPT_ENGINE_RUN_ACTIONS)  # ret 0xc
    a.emit(0xC7, 0x05, at(_RESULT), u32(1))  # mov dword [result], 1
    a.label("leave")
    a.emit(0xB9, at(_GUARD))  # mov ecx, guard
    a.call_absolute(SCRIPT_SCOPE_LEAVE)  # ret
    a.jmp("restore")
    a.label("no_player")
    a.emit(0xC7, 0x05, at(_RESULT), u32(NO_PLAYER))  # mov dword [result], -1
    a.label("restore")
    a.emit(0x8F, 0x86, u32(SCRIPT_ENGINE_CURRENT_OBJECT))  # pop dword [esi+object]
    a.emit(0x8F, 0x86, u32(SCRIPT_ENGINE_CURRENT_PLAYER))  # pop dword [esi+player]
    # The result is complete before `done` moves, so the controller never reads half of one.
    a.emit(0xA1, at(_REQUEST))  # mov eax, [request]
    a.emit(0xA3, at(_DONE))  # mov [done], eax
    a.emit(0x61)  # popad
    a.emit(0xC3)  # ret
    code = a.finish()
    if CODE_OFFSET + len(code) > CAVE_SIZE:
        raise AssertionError("the gate cave outgrew its allocation")
    return head + code


@dataclass(frozen=True)
class GateState:
    mode: int
    target: int
    lease: int
    hits: int
    frame: int | None

    @property
    def paused(self) -> bool:
        return self.mode == Mode.PAUSED


class FrameGate:
    """Pause, resume and step the simulation of one running game, and run commands in it.

    `attach` installs the hook (or adopts one an earlier session left, replacing it when an older
    version laid it out); `close` puts the game back running and takes the hook out. Use it as a
    context manager so an exception cannot leave the game paused - and if the process dies
    anyway, the lease lets the game go on its own.
    """

    def __init__(self, process: LiveProcess, lease: int = DEFAULT_LEASE) -> None:
        self.process = process
        self.patcher = LivePatcher(process)
        self.lease = lease
        self.cave: int | None = None
        self.adopted = False
        self._renewer: threading.Thread | None = None
        self._stop = threading.Event()
        # One command at a time: the renewer thread and a caller must not interleave the fields.
        self._command_lock = threading.Lock()

    def __enter__(self) -> FrameGate:
        self.attach()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _u32(self, address: int) -> int | None:
        raw = self.process.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def game_logic(self) -> int | None:
        value = self._u32(THE_GAME_LOGIC)
        return value or None

    def frame(self) -> int | None:
        logic = self.game_logic()
        return self._u32(logic + GAME_LOGIC_FRAME) if logic else None

    def _existing_cave(self, current: bytes | None) -> int | None:
        """The head of the cave an earlier session's hook leads to, if the site holds one."""
        if current is None or current == FRAME_DISPATCHER_PAUSE_CALL_BYTES:
            return None
        target = call_target(FRAME_DISPATCHER_PAUSE_CALL, current)
        if target is None:
            return None
        base = allocation_base(target)
        return base if self.process.read(base, len(MAGIC)) == MAGIC else None

    def attach(self, allow_network: bool = False) -> None:
        logic = self.game_logic()
        mode = self._u32(logic + GAME_LOGIC_GAME_MODE) if logic else None
        if mode in NETWORK_GAME_MODES and not allow_network:
            raise NetworkGameRefused(
                f"this is a network game (mode {mode}); pausing one peer stalls it for everyone"
            )
        site = FRAME_DISPATCHER_PAUSE_CALL
        current = self.process.read(site, 5)
        base = self._existing_cave(current)
        if base is not None and current is not None:
            if self._u32(base + 4) == VERSION:
                self.cave = base
                self.adopted = True
                self.patcher.adopt(base)
                self.patcher.hook(site, FRAME_DISPATCHER_PAUSE_CALL_BYTES, current)
                self._start_renewing()
                return
            # Another version's cave: put the call back, let it go, and lay out this one.
            old = LivePatcher(self.process)
            old.adopt(base)
            old.hook(site, FRAME_DISPATCHER_PAUSE_CALL_BYTES, current)
            notes = old.close()
            if notes:
                raise LivePatchError("an older gate could not be removed: " + "; ".join(notes))
        base = self.patcher.allocate(CAVE_SIZE)
        if not self.process.write(base, build_gate_cave(base)):
            raise LivePatchError("writing the gate cave failed")
        self.cave = base
        self.patcher.hook(
            site, FRAME_DISPATCHER_PAUSE_CALL_BYTES, call_bytes(site, base + CODE_OFFSET)
        )
        self._start_renewing()

    @property
    def mode_address(self) -> int:
        """The address of the mode field, which a breakpoint writes "held" into."""
        return self._field(_MODE)

    def _field(self, offset: int) -> int:
        if self.cave is None:
            raise LivePatchError("not attached")
        return self.cave + offset

    def _set(self, offset: int, value: int) -> None:
        if not self.process.write(self._field(offset), struct.pack("<I", value)):
            raise LivePatchError(f"writing the gate's control block at +0x{offset:X} failed")

    def state(self) -> GateState:
        raw = self.process.read(self._field(_MODE), 0x10)
        if raw is None:
            raise LivePatchError("the gate's control block is unreadable - the game exited?")
        mode, target, lease, hits = struct.unpack("<IIII", raw)
        return GateState(mode, target, lease, hits, self.frame())

    def renew(self) -> None:
        self._set(_LEASE, self.lease)

    def _start_renewing(self) -> None:
        self.renew()
        self._stop.clear()
        self._renewer = threading.Thread(target=self._renew_loop, daemon=True)
        self._renewer.start()

    def _renew_loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self.renew()
            except LivePatchError:
                return

    def pause(self) -> None:
        self.renew()
        self._set(_MODE, Mode.PAUSED)

    def resume(self) -> None:
        self._set(_MODE, Mode.RUN)

    def run_until(self, frame: int) -> None:
        """Let the simulation run until logic frame `frame`, then hold it there."""
        self.renew()
        self._set(_TARGET, frame)
        self._set(_MODE, Mode.RUN_UNTIL)

    def step(self, frames: int = 1, timeout: float = 5.0) -> int | None:
        """Advance exactly `frames` logic frames from where it is held; returns the new frame."""
        start = self.frame()
        if start is None:
            raise LivePatchError("no game logic - is a match running?")
        self.run_until(start + frames)
        return self.wait_paused(timeout)

    def wait_paused(self, timeout: float = 5.0) -> int | None:
        """Block until the gate holds the game, returning the frame; None on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.state().paused:
                return self.frame()
            time.sleep(0.02)
        return None

    def command(
        self, command: Command, script: int, side: int, name: int, timeout: float = 5.0
    ) -> int:
        """Run `command` on `script` in the game's own thread, in `side`'s scope, and return the
        result: the evaluation for `EVALUATE`, 1 when actions ran and 0 for an empty list.

        Raises when the game does not take the command within `timeout` - a game at a load
        screen or minimised may not be running its dispatcher.
        """
        with self._command_lock:
            request = self._u32(self._field(_REQUEST))
            if request is None:
                raise LivePatchError("the gate's control block is unreadable - the game exited?")
            fields = struct.pack("<IIII", command, script, side, name)
            if not self.process.write(self._field(_COMMAND), fields):
                raise LivePatchError("writing the command failed")
            # The fields are complete before `request` moves, so the cave never runs half of one.
            request = (request + 1) & 0xFFFFFFFF
            self._set(_REQUEST, request)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._u32(self._field(_DONE)) == request:
                    result = self._u32(self._field(_RESULT))
                    if result is None:
                        break
                    if result == NO_PLAYER:
                        raise LivePatchError(f"side {side} has no player")
                    return result
                time.sleep(0.01)
            raise LivePatchError("the game did not run the command - is it at a load screen?")

    def close(self) -> list[str]:
        """Resume the game and take the hook out. Returns notes on anything left in place."""
        self._stop.set()
        if self._renewer is not None:
            self._renewer.join(timeout=2.0)
        if self.cave is not None:
            try:
                self.resume()
            except LivePatchError:
                pass
        notes = self.patcher.close()
        self.cave = None
        return notes
