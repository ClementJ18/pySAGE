"""The running game's scripts, as the editor sees them: attach read-only, poll, and say for each
script in the open map what the game is doing with it.

Attaching is read-only: it writes nothing and needs no patch, so it can attach to any game on the
machine - one Jump To Game started or one started by hand. Recording, breakpoints, pause and step
hook the game on top of that, only once asked for (`LiveSession`). What the session cannot do is
tell two different maps apart by content, so it compares the running map's path with the open
document's and the panels only overlay live state when the two are the same map.

The game does not run a map's scripts as the map lays them out. A skirmish rebuilds the sides - one
per occupied slot, plus the civilian and creep sides - and merges each AI's library scripts into
its side, so the live tree is keyed by player and name, never by position. A script is looked up
under the player that owns it in the map first, and by name alone after that.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePath, PureWindowsPath

from sage_live.backends import game_speed
from sage_live.backends.base import ConnectionRefused
from sage_live.backends.live_patch import LivePatchError, WindowsProcess
from sage_live.backends.memory import MemoryBackend, ProcessMemory, find_game_processes
from sage_live.backends.script_debugger import Command, FrameGate
from sage_live.backends.script_trace import BreakpointHit, ScriptTrace, TraceEvent
from sage_live.backends.scripts import (
    LiveScript,
    LiveScriptGroup,
    ScriptTree,
    ScriptVariable,
    read_script_tree,
    read_script_variables,
)
from sage_patch.addresses import (
    GAME_INFO_MAP,
    GAME_LOGIC_GAME_MODE,
    LOGIC_FRAMES_PER_SECOND,
    NETWORK_GAME_MODES,
    SCRIPT_ACTIVE,
    SCRIPT_GROUP_ACTIVE,
    SCRIPT_NEXT_FRAME,
    TERRAIN_LOGIC_MAP_PATH,
    THE_GAME_INFO,
    THE_GAME_LOGIC,
    THE_SKIRMISH_GAME_INFO,
    THE_TERRAIN_LOGIC,
)
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.jump import launch_name

__all__ = [
    "LiveAccessDenied",
    "LiveAttachError",
    "LiveIndex",
    "LiveSession",
    "LiveSnapshot",
    "LiveState",
    "LiveStatus",
    "document_keys",
    "map_key",
    "side_label",
]

# The engine's own rate when the read fails; a timer counts down this many ticks a second.
_DEFAULT_LOGIC_RATE = 5


class LiveAttachError(RuntimeError):
    """No game to attach to, or one this process may not read - or hook, for the features that
    write into it."""


class LiveAccessDenied(LiveAttachError):
    """The game runs as administrator and the editor does not: no amount of waiting fixes it."""


def side_label(side: int, player: str) -> str:
    """A side as the editor names it: its player, `(neutral)` for the player with no name - always
    the first, in a map and in a running game - and its index where no player is known."""
    if player:
        return player
    return "(neutral)" if side == 0 else f"side {side}"


class LiveStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    # A one-shot the map made active that the game has since switched off: it ran and succeeded.
    FIRED = "fired"


@dataclass(frozen=True)
class LiveState:
    """What the game holds for one script or group, and which of its sides holds it."""

    status: LiveStatus
    side: int
    player: str
    # How the live flag compares with the map's: True when the game changed it.
    changed: bool
    script: LiveScript | None = None
    group: LiveScriptGroup | None = None
    # How many sides carry an item of this name; more than one is normal for AI library scripts.
    copies: int = 1

    def describe(self, frame: int, rate: int) -> str:
        """One line for a tooltip or the script page."""
        words = [self.status.value]
        if self.changed and self.status is not LiveStatus.FIRED:
            words.append("(changed by the game)")
        script = self.script
        if script is not None and script.delay_seconds and self.status is LiveStatus.ACTIVE:
            due = script.next_frame - frame
            if due > 0:
                words.append(f"- evaluates again in {due / rate:.1f} s")
        where = f"on {side_label(self.side, self.player)}"
        if self.copies > 1:
            where += f" (and {self.copies - 1} other side{'s' if self.copies > 2 else ''})"
        return f"{' '.join(words)} {where}"


@dataclass(frozen=True)
class LiveSnapshot:
    """One poll of the running game."""

    map_path: str
    frame: int
    logic_rate: int
    tree: ScriptTree
    variables: tuple[ScriptVariable, ...]
    # Side index to player name. Side `i` is player `i`.
    players: dict[int, str] = field(default_factory=dict)
    # The scripts fired since the last poll, when a trace is recording, and how many were lost
    # because the ring filled before they were read.
    trace: tuple[TraceEvent, ...] = ()
    dropped: int = 0
    # Whether the frame gate holds the game, and the last breakpoint hit - both only while the
    # hooks that know them are in.
    paused: bool = False
    hit: BreakpointHit | None = None
    # How many times faster than normal the game is paced; 1 at normal speed.
    speed: int = 1

    @property
    def script_count(self) -> int:
        return sum(len(side.all_scripts()) for side in self.tree.sides)


def map_key(path: str | PurePath) -> str:
    """A map's identity for comparing the running game with the open file: its name, in lower
    case. The game reports `maps/map mp westfold` for a shipped map and a full path to the `.map`
    for a user map; both reduce to the file stem."""
    text = str(path).replace("\\", "/").rstrip("/")
    name = PureWindowsPath(text).name
    return name[:-4].lower() if name.lower().endswith(".map") else name.lower()


def document_keys(document: MapDocument) -> set[str]:
    """Every name the running game could report for the open map: its file's, and the copy Jump
    To Game makes of a map with no file of its own."""
    keys = {map_key(launch_name(document.title))}
    if document.path is not None:
        keys.add(map_key(document.path))
    return keys


def _walk_groups(groups: tuple[LiveScriptGroup, ...]) -> Iterator[LiveScriptGroup]:
    for group in groups:
        yield group
        yield from _walk_groups(group.groups)


class LiveIndex:
    """A snapshot keyed for lookup by the editor: `(player, name)` and name alone."""

    def __init__(self, snapshot: LiveSnapshot) -> None:
        self.snapshot = snapshot
        self._scripts: dict[str, list[tuple[int, LiveScript]]] = {}
        self._groups: dict[str, list[tuple[int, LiveScriptGroup]]] = {}
        self._at: dict[int, tuple[int, LiveScript]] = {}
        for side in snapshot.tree.sides:
            for script in side.all_scripts():
                self._scripts.setdefault(script.name.lower(), []).append((side.index, script))
                self._at[script.address] = (side.index, script)
            for group in _walk_groups(side.groups):
                self._groups.setdefault(group.name.lower(), []).append((side.index, group))

    def _player(self, side: int) -> str:
        return self.snapshot.players.get(side, "")

    def addresses(self, name: str) -> list[int]:
        """The `Script *` of every live copy of the script `name`, on every side."""
        return [script.address for _, script in self._scripts.get(name.casefold(), [])]

    def at(self, address: int) -> tuple[str, LiveScript] | None:
        """The player and script a trace event's `Script *` names, or None for one the tree
        does not hold."""
        found = self._at.get(address)
        if found is None:
            return None
        side, script = found
        return side_label(side, self._player(side)), script

    def _pick[T](self, found: list[tuple[int, T]], player: str) -> tuple[int, T]:
        wanted = player.lower()
        for side, item in found:
            if wanted and self._player(side).lower() == wanted:
                return side, item
        return found[0]

    def script(self, player: str, name: str, authored_active: bool) -> LiveState | None:
        """The live state of the map's script `name` owned by `player`, or None when the game
        has no script of that name."""
        found = self._scripts.get(name.lower())
        if not found:
            return None
        side, script = self._pick(found, player)
        if script.one_shot and script.authored_active and not script.active:
            status = LiveStatus.FIRED
        else:
            status = LiveStatus.ACTIVE if script.active else LiveStatus.INACTIVE
        return LiveState(
            status=status,
            side=side,
            player=self._player(side),
            changed=script.active != authored_active,
            script=script,
            copies=len(found),
        )

    def group(self, player: str, name: str, authored_active: bool) -> LiveState | None:
        found = self._groups.get(name.lower())
        if not found:
            return None
        side, group = self._pick(found, player)
        return LiveState(
            status=LiveStatus.ACTIVE if group.active else LiveStatus.INACTIVE,
            side=side,
            player=self._player(side),
            changed=group.active != authored_active,
            group=group,
            copies=len(found),
        )


class LiveSession:
    """An attach to one running game: read-only until a feature that hooks it is asked for.

    Reading needs nothing but a read handle. Recording, breakpoints, pause and step write code into
    the game, through a second handle opened only when the first of them is used: the trace hooks
    (`ScriptTrace`) carry recording and breakpoints, the frame gate (`FrameGate`) carries pause and
    step and is what a breakpoint holds. Each set of hooks goes in when first needed and comes out
    when nothing needs it any more, or on `close`. Fast-forward writes no code, only the frame cap
    (`sage_live.backends.game_speed`), and a session that raised it puts it back on `unhook`.
    """

    def __init__(self, memory: ProcessMemory, backend: MemoryBackend, pid: int) -> None:
        self.memory = memory
        self.backend = backend
        self.pid = pid
        self._writer: WindowsProcess | None = None
        self._trace: ScriptTrace | None = None
        self._gate: FrameGate | None = None
        self._recording = False
        self._breakpoints: dict[int, int] = {}
        self._speed = 1

    @property
    def recording(self) -> bool:
        return self._recording

    def _hooks(self) -> WindowsProcess:
        if self._writer is None:
            try:
                self._writer = WindowsProcess(self.pid)
            except (PermissionError, RuntimeError) as exc:
                raise LiveAttachError(f"The game cannot be hooked: {exc}") from exc
        return self._writer

    def _ensure_trace(self) -> ScriptTrace:
        if self._trace is None:
            trace = ScriptTrace(self._hooks())
            try:
                trace.attach(recording=self._recording)
            except LivePatchError as exc:
                raise LiveAttachError(f"The game could not be hooked: {exc}") from exc
            self._trace = trace
        return self._trace

    def _ensure_gate(self) -> FrameGate:
        if self._gate is None:
            gate = FrameGate(self._hooks())
            try:
                gate.attach()
            except LivePatchError as exc:
                raise LiveAttachError(f"The game could not be paused: {exc}") from exc
            self._gate = gate
        return self._gate

    def set_recording(self, on: bool) -> list[str]:
        """Record every script the game fires, or stop. Returns notes on anything left behind."""
        self._recording = on
        if on:
            self._ensure_trace().set_recording(True)
            return []
        if self._trace is not None:
            self._write(lambda trace: trace.set_recording(False))
        return self._drop_trace_if_idle()

    def set_breakpoints(self, table: dict[int, int]) -> list[str]:
        """Break on `{Script *: kind mask}` - the whole table, replacing the last one."""
        if table == self._breakpoints:
            return []
        if table:
            try:
                trace = self._ensure_trace()
                gate = self._ensure_gate()
                trace.set_gate(gate.mode_address)
                trace.set_breakpoints(table)
            except LivePatchError as exc:
                raise LiveAttachError(f"The breakpoints could not be set: {exc}") from exc
            # Stored only once written, so a failure is retried by the next call.
            self._breakpoints = dict(table)
            return []
        self._breakpoints = {}
        if self._trace is not None:
            self._write(lambda trace: trace.set_breakpoints({}))
        return self._drop_trace_if_idle()

    def _write(self, action: Callable[[ScriptTrace], None]) -> None:
        trace = self._trace
        if trace is None:
            return
        try:
            action(trace)
        except LivePatchError:
            # The game is gone or going; the hooks go with it.
            pass

    def _drop_trace_if_idle(self) -> list[str]:
        if self._trace is None or self._recording or self._breakpoints:
            return []
        trace, self._trace = self._trace, None
        try:
            return trace.close()
        except LivePatchError as exc:
            return [f"the trace hooks could not be taken out: {exc}"]

    def pause(self) -> None:
        try:
            self._ensure_gate().pause()
        except LivePatchError as exc:
            raise LiveAttachError(f"The game could not be paused: {exc}") from exc

    def resume(self) -> None:
        if self._gate is None:
            return
        try:
            self._gate.resume()
        except LivePatchError as exc:
            raise LiveAttachError(f"The game could not be resumed: {exc}") from exc

    def step(self, frames: int) -> None:
        """Let `frames` logic frames run, then hold again. Returns at once; a poll shows it."""
        gate = self._ensure_gate()
        frame = gate.frame()
        if frame is None:
            raise LiveAttachError("No match is running.")
        try:
            gate.run_until(frame + frames)
        except LivePatchError as exc:
            raise LiveAttachError(f"The game could not be stepped: {exc}") from exc

    def set_speed(self, multiplier: int) -> None:
        """Pace the game at `multiplier` times normal, 1 for normal. Refused in a network game,
        which the peers pace together."""
        try:
            game_speed.set_speed(self._changes(), multiplier)
        except LivePatchError as exc:
            raise LiveAttachError(f"The game's speed could not be changed: {exc}") from exc
        self._speed = multiplier

    def _changes(self) -> WindowsProcess:
        """The handle a trigger writes through, refused in a network game: every trigger changes
        what the simulation does, and a peer that did not see it would drop out of the match."""
        logic = self._u32(THE_GAME_LOGIC)
        mode = self._u32(logic + GAME_LOGIC_GAME_MODE) if logic else None
        if mode in NETWORK_GAME_MODES:
            raise LiveAttachError("This is a network game; changing its scripts is refused.")
        return self._hooks()

    def _poke(self, address: int, data: bytes) -> None:
        if not self._changes().write(address, data):
            raise LiveAttachError(f"Writing the game at 0x{address:08X} failed.")

    def set_script_active(self, script: LiveScript, active: bool) -> None:
        """Switch a script on or off in the game - its live flag, the one the due check reads."""
        self._poke(script.address + SCRIPT_ACTIVE, bytes([int(active)]))

    def rearm(self, script: LiveScript) -> None:
        """Make a fired one-shot able to fire again: due now, and on."""
        self._poke(script.address + SCRIPT_NEXT_FRAME, struct.pack("<I", 0))
        self._poke(script.address + SCRIPT_ACTIVE, b"\x01")

    def set_group_active(self, group: LiveScriptGroup, active: bool) -> None:
        self._poke(group.address + SCRIPT_GROUP_ACTIVE, bytes([int(active)]))

    def set_variable(self, variable: ScriptVariable, value: int) -> None:
        """Set a counter, a flag (0 or 1) or a timer (in logic frames) that the game already has.
        A variable a script has not yet created cannot be made from here."""
        if not variable.address:
            raise LiveAttachError(f"{variable.key} has no record to write.")
        if variable.kind == "flag":
            self._poke(variable.address, bytes([1 if value else 0]))
        else:
            self._poke(variable.address, struct.pack("<i", value))

    def _run(self, command: Command, script: LiveScript, side: int) -> int:
        self._changes()
        gate = self._ensure_gate()
        try:
            return gate.command(command, script.address, side, script.name_address)
        except LivePatchError as exc:
            raise LiveAttachError(f"The game did not run it: {exc}") from exc

    def evaluate(self, script: LiveScript, side: int) -> bool:
        """Test a script's conditions now, in its player's scope, without running anything."""
        return bool(self._run(Command.EVALUATE, script, side))

    def run_actions(self, script: LiveScript, side: int, false_actions: bool = False) -> bool:
        """Run a script's true (or false) actions now, in its player's scope, whatever its
        conditions say. False when that list is empty."""
        command = Command.RUN_FALSE_ACTIONS if false_actions else Command.RUN_TRUE_ACTIONS
        return bool(self._run(command, script, side))

    def unhook(self) -> list[str]:
        """Take every hook out and put the game back running. Never raises: it runs on Detach,
        and when the game has just been closed - a game that is gone took the hooks with it."""
        self._recording = False
        self._breakpoints = {}
        notes: list[str] = []
        if self._speed != 1 and self._writer is not None:
            try:
                game_speed.set_speed(self._writer, 1)
            except LivePatchError as exc:
                notes.append(f"the game was left fast: {exc}")
            self._speed = 1
        trace, gate, writer = self._trace, self._gate, self._writer
        self._trace = self._gate = self._writer = None
        for closing in (trace, gate):
            if closing is None:
                continue
            try:
                notes += closing.close()
            except LivePatchError as exc:
                notes.append(f"a hook could not be taken out: {exc}")
        if writer is not None:
            writer.close()
        return notes

    @classmethod
    def attach(cls) -> LiveSession:
        pids = find_game_processes()
        if not pids:
            raise LiveAttachError("No running game was found.")
        try:
            memory = ProcessMemory(pids[0])
        except PermissionError as exc:
            raise LiveAccessDenied(
                "The game runs as administrator, so the editor must be run as administrator "
                "to read it."
            ) from exc
        except RuntimeError as exc:
            raise LiveAttachError(str(exc)) from exc
        backend = MemoryBackend(memory, read_production=False)
        try:
            backend.connect()
        except ConnectionRefused as exc:
            # `connect` refuses another build, and also a game still at the main menu - which is
            # fine to attach to, since a match may start later. Only the first is fatal.
            if backend.identity is None or "TheGameLogic" not in str(exc):
                memory.close()
                raise LiveAttachError(str(exc)) from exc
        return cls(memory, backend, pids[0])

    def _u32(self, address: int) -> int:
        raw = self.memory.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else 0

    def _ascii_string(self, address: int) -> str:
        """The `AsciiString` at `address`: a pointer to `{refCount, UInt16 length, ...}` with the
        characters at `+8`, null for the empty string."""
        block = self._u32(address)
        header = self.memory.read(block + 4, 2) if block else None
        if not header:
            return ""
        (length,) = struct.unpack("<H", header)
        raw = self.memory.read(block + 8, length) if length else None
        return raw.decode("latin-1", errors="replace") if raw else ""

    def map_path(self) -> str:
        """The loaded map, from the terrain logic; else `GameInfo::m_map`, from whichever of the
        two game-info globals is set. A `-file` start sets neither global."""
        terrain = self._u32(THE_TERRAIN_LOGIC)
        path = self._ascii_string(terrain + TERRAIN_LOGIC_MAP_PATH) if terrain else ""
        for global_ in (THE_GAME_INFO, THE_SKIRMISH_GAME_INFO):
            if path:
                break
            info = self._u32(global_)
            path = self._ascii_string(info + GAME_INFO_MAP) if info else ""
        return path

    def alive(self) -> bool:
        return self.memory.read(THE_GAME_INFO, 4) is not None

    def poll(self) -> LiveSnapshot | None:
        """The game's scripts now, or None when no map is loaded (the menus, a load screen)."""
        # The tree first, so every event read after it names a script the tree already holds.
        tree = read_script_tree(self.memory.read)
        trace = self._read_trace()
        if tree is None:
            return None
        rate = self._u32(LOGIC_FRAMES_PER_SECOND) or _DEFAULT_LOGIC_RATE
        return LiveSnapshot(
            map_path=self.map_path(),
            frame=self.backend.frame(),
            logic_rate=rate,
            tree=tree,
            variables=tuple(read_script_variables(self.memory.read)),
            players={player.index: player.name for player in self.backend.read_players()},
            trace=tuple(trace),
            dropped=self._trace.dropped if self._trace is not None else 0,
            paused=self._paused(),
            hit=self._trace.hit() if self._trace is not None else None,
            speed=game_speed.speed(self.memory.read),
        )

    def _paused(self) -> bool:
        if self._gate is None:
            return False
        try:
            return self._gate.state().paused
        except LivePatchError:
            return False

    def _read_trace(self) -> list[TraceEvent]:
        if self._trace is None or not self._recording:
            return []
        try:
            return self._trace.read()
        except LivePatchError:
            return []

    def close(self) -> list[str]:
        notes = self.unhook()
        self.memory.close()
        return notes
