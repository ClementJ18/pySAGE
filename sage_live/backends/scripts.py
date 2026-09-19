"""The running game's map scripts: every side's script tree, and the counters and flags they keep.

Read-only, like the rest of `MemoryBackend` - this only follows pointers, so it is safe against any
running game and needs no patch. It is the read half of the script debugger
(`sage_patch/docs/script-debugger.md`); the write half enables, re-arms and triggers what this
names.

The tree is not a plain linked list. A `ScriptList` keeps two chains of small nodes (top-level
groups, top-level scripts) over two name-keyed pools, and the node leads to the object through the
pool entry, which is also where the **name** lives - a `Script` does not hold its own. Groups nest,
so a group carries a child-group chain beside its script chain. A node whose generation no longer
matches its entry is stale and the engine's own walk skips it; so does this, so what comes back is
what the engine would run.

Every walk is bounded. A game can be read mid-teardown, where a chain can point anywhere, and a
cycle there must end the walk rather than hang the reader.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass

from sage_patch.addresses import (
    SCRIPT_ACTIVE,
    SCRIPT_AUTHORED_ACTIVE,
    SCRIPT_COUNTER_IS_SECONDS,
    SCRIPT_COUNTER_IS_TIMER,
    SCRIPT_COUNTER_VALUE,
    SCRIPT_DELAY_SECONDS,
    SCRIPT_EASY,
    SCRIPT_ENGINE_COUNTER_MAP,
    SCRIPT_ENGINE_DIFFICULTY,
    SCRIPT_ENGINE_FLAG_MAP,
    SCRIPT_FALSE_ACTIONS,
    SCRIPT_GROUP_ACTIVE,
    SCRIPT_GROUP_GROUPS,
    SCRIPT_GROUP_SCRIPTS,
    SCRIPT_GROUP_SUBROUTINE,
    SCRIPT_HARD,
    SCRIPT_LIST_ENTRY_GENERATION,
    SCRIPT_LIST_ENTRY_NAME,
    SCRIPT_LIST_ENTRY_OBJECTS,
    SCRIPT_LIST_ENTRY_SIZE,
    SCRIPT_LIST_GROUP_ENTRIES,
    SCRIPT_LIST_GROUPS,
    SCRIPT_LIST_SCRIPT_ENTRIES,
    SCRIPT_LIST_SCRIPTS,
    SCRIPT_NEXT_FRAME,
    SCRIPT_NODE_GENERATION,
    SCRIPT_NODE_INDEX,
    SCRIPT_NODE_NEXT,
    SCRIPT_NORMAL,
    SCRIPT_ONE_SHOT,
    SCRIPT_SEQUENTIAL,
    SCRIPT_SUBROUTINE,
    SCRIPT_TRUE_ACTIONS,
    SIDES_INFO_SCRIPT_LIST,
    SIDES_INFO_STRIDE,
    SIDES_LIST_SIDE_COUNT,
    SIDES_LIST_SIDES,
    STD_MAP_NODE_VALUE,
    THE_SCRIPT_ENGINE,
    THE_SIDES_LIST,
)

__all__ = [
    "LiveScript",
    "LiveScriptGroup",
    "ScriptTree",
    "ScriptVariable",
    "SideScripts",
    "read_script_tree",
    "read_script_variables",
]

Read = Callable[[int, int], bytes | None]

# `SidesList` holds 20 live sides; anything above that is a torn read, not a bigger game.
_MAX_SIDES = 20
# Far above any shipped or modded map, and small enough that a cycle ends quickly.
_MAX_NODES = 50_000
_MAX_DEPTH = 64
_MIN_PTR = 0x10000
_MAX_PTR = 0x7FFFFFFF
# An `AsciiString` is one pointer to `{refcount, u16 length, u16 capacity, chars...}`.
_STRING_LENGTH = 4
_STRING_CHARS = 8
_NAME_LIMIT = 256

# The std::map node links the engine's own iterator increment (`0x00423EA0`) follows.
_MAP_PARENT = 0x04
_MAP_LEFT = 0x08
_MAP_RIGHT = 0x0C
# Counter and flag keys are `(scope, name)`: two `AsciiString`s ahead of the value.
_MAP_KEY_SCOPE = 0x10
_MAP_KEY_NAME = 0x14


@dataclass(frozen=True)
class LiveScript:
    """One script as the engine holds it right now.

    `active` is the live flag - the one a one-shot clears when it fires and the due check reads -
    while `authored_active` is the map's own, so the two differing means the script has fired (or
    an action has toggled it). `next_frame` is the first logic frame it may evaluate again.
    """

    name: str
    address: int
    active: bool
    authored_active: bool
    one_shot: bool
    subroutine: bool
    easy: bool
    normal: bool
    hard: bool
    delay_seconds: int
    sequential: bool
    next_frame: int
    # The enclosing group names, outermost first; empty for a top-level script.
    path: tuple[str, ...] = ()
    # The pool entry's name `AsciiString`, which is what the engine passes when it runs the
    # script's actions; and whether each action list has anything in it.
    name_address: int = 0
    has_true_actions: bool = False
    has_false_actions: bool = False


@dataclass(frozen=True)
class LiveScriptGroup:
    name: str
    address: int
    active: bool
    subroutine: bool
    scripts: tuple[LiveScript, ...]
    groups: tuple[LiveScriptGroup, ...]
    path: tuple[str, ...] = ()


@dataclass(frozen=True)
class SideScripts:
    """One side's scripts. Side `index` is player `index`; the engine walks both with one index."""

    index: int
    scripts: tuple[LiveScript, ...]
    groups: tuple[LiveScriptGroup, ...]

    def all_scripts(self) -> list[LiveScript]:
        """Every script on the side, groups flattened, in the engine's evaluation order."""
        out = list(self.scripts)
        stack = list(reversed(self.groups))
        while stack:
            group = stack.pop()
            out.extend(group.scripts)
            stack.extend(reversed(group.groups))
        return out


@dataclass(frozen=True)
class ScriptTree:
    sides: tuple[SideScripts, ...]
    # The game difficulty the due check falls back to when the evaluated player has no AI.
    difficulty: int | None

    def find(self, name: str) -> list[tuple[int, LiveScript]]:
        """Every `(side, script)` named `name`. More than one side can carry the same name."""
        return [
            (side.index, script)
            for side in self.sides
            for script in side.all_scripts()
            if script.name == name
        ]


@dataclass(frozen=True)
class ScriptVariable:
    """A counter, timer or flag. `scope` is the owning player's name, empty for a global.

    A timer holds logic ticks **remaining**; `seconds` only records how it was authored.
    """

    kind: str  # "counter", "timer" or "flag"
    scope: str
    name: str
    value: int
    seconds: bool = False
    address: int = 0

    @property
    def key(self) -> str:
        """The engine's own spelling, `scope/name`, which a script may also write explicitly."""
        return f"{self.scope}/{self.name}"


class _Reader:
    def __init__(self, read: Read) -> None:
        self.read = read
        self.budget = _MAX_NODES

    def u32(self, address: int) -> int | None:
        raw = self.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def i32(self, address: int) -> int | None:
        raw = self.read(address, 4)
        return struct.unpack("<i", raw)[0] if raw else None

    def i16(self, address: int) -> int | None:
        raw = self.read(address, 2)
        return struct.unpack("<h", raw)[0] if raw else None

    def pointer(self, address: int) -> int | None:
        value = self.u32(address)
        if value is None or not (_MIN_PTR <= value <= _MAX_PTR):
            return None
        return value

    def ascii(self, address: int) -> str:
        block = self.pointer(address)
        if block is None:
            return ""
        # The block's own length, so a read never runs past the allocation into an unmapped page.
        header = self.read(block + _STRING_LENGTH, 2)
        if header is None:
            return ""
        (length,) = struct.unpack("<H", header)
        raw = self.read(block + _STRING_CHARS, min(length, _NAME_LIMIT)) if length else b""
        if raw is None:
            return ""
        return raw.split(b"\x00")[0].decode("latin-1", errors="replace")

    def spend(self) -> bool:
        self.budget -= 1
        return self.budget >= 0

    def chain(self, head: int | None, entries: int) -> list[tuple[str, int, int]]:
        """`(name, object, name address)` for every live node on one chain, in order.

        `entries` is the pool's entry array. A node is kept only when its generation matches its
        entry's, which is the engine's own validity test for the walk.
        """
        out: list[tuple[str, int, int]] = []
        seen: set[int] = set()
        node = head
        while node is not None and node not in seen and self.spend():
            seen.add(node)
            index = self.i32(node + SCRIPT_NODE_INDEX)
            generation = self.i32(node + SCRIPT_NODE_GENERATION)
            if index is not None and generation is not None and index >= 0:
                entry = entries + index * SCRIPT_LIST_ENTRY_SIZE
                current = self.i16(entry + SCRIPT_LIST_ENTRY_GENERATION)
                objects = self.pointer(entry + SCRIPT_LIST_ENTRY_OBJECTS)
                if current == generation and objects is not None:
                    name = entry + SCRIPT_LIST_ENTRY_NAME
                    out.append((self.ascii(name), objects + 4, name))
            node = self.pointer(node + SCRIPT_NODE_NEXT)
        return out

    def flag(self, address: int) -> bool:
        raw = self.read(address, 1)
        return bool(raw and raw[0])

    def script(
        self, name: str, address: int, path: tuple[str, ...], name_address: int = 0
    ) -> LiveScript | None:
        raw = self.read(address, SCRIPT_ACTIVE + 1)
        if raw is None:
            return None
        (delay,) = struct.unpack_from("<i", raw, SCRIPT_DELAY_SECONDS)
        (next_frame,) = struct.unpack_from("<I", raw, SCRIPT_NEXT_FRAME)
        (true_actions,) = struct.unpack_from("<I", raw, SCRIPT_TRUE_ACTIONS)
        (false_actions,) = struct.unpack_from("<I", raw, SCRIPT_FALSE_ACTIONS)
        return LiveScript(
            name=name,
            address=address,
            active=bool(raw[SCRIPT_ACTIVE]),
            authored_active=bool(raw[SCRIPT_AUTHORED_ACTIVE]),
            one_shot=bool(raw[SCRIPT_ONE_SHOT]),
            subroutine=bool(raw[SCRIPT_SUBROUTINE]),
            easy=bool(raw[SCRIPT_EASY]),
            normal=bool(raw[SCRIPT_NORMAL]),
            hard=bool(raw[SCRIPT_HARD]),
            delay_seconds=delay,
            sequential=bool(raw[SCRIPT_SEQUENTIAL]),
            next_frame=next_frame,
            path=path,
            name_address=name_address,
            has_true_actions=bool(true_actions),
            has_false_actions=bool(false_actions),
        )

    def scripts(
        self, script_list: int, head: int | None, path: tuple[str, ...]
    ) -> tuple[LiveScript, ...]:
        entries = self.pointer(script_list + SCRIPT_LIST_SCRIPT_ENTRIES)
        if entries is None:
            return ()
        found = (
            self.script(name, obj, path, name_address)
            for name, obj, name_address in self.chain(head, entries)
        )
        return tuple(script for script in found if script is not None)

    def groups(
        self, script_list: int, head: int | None, path: tuple[str, ...]
    ) -> tuple[LiveScriptGroup, ...]:
        entries = self.pointer(script_list + SCRIPT_LIST_GROUP_ENTRIES)
        if entries is None or len(path) >= _MAX_DEPTH:
            return ()
        out = []
        for name, obj, _ in self.chain(head, entries):
            inner = (*path, name)
            out.append(
                LiveScriptGroup(
                    name=name,
                    address=obj,
                    active=self.flag(obj + SCRIPT_GROUP_ACTIVE),
                    subroutine=self.flag(obj + SCRIPT_GROUP_SUBROUTINE),
                    scripts=self.scripts(
                        script_list, self.pointer(obj + SCRIPT_GROUP_SCRIPTS), inner
                    ),
                    groups=self.groups(script_list, self.pointer(obj + SCRIPT_GROUP_GROUPS), inner),
                    path=path,
                )
            )
        return tuple(out)

    def side(self, index: int, script_list: int) -> SideScripts:
        return SideScripts(
            index=index,
            scripts=self.scripts(script_list, self.pointer(script_list + SCRIPT_LIST_SCRIPTS), ()),
            groups=self.groups(script_list, self.pointer(script_list + SCRIPT_LIST_GROUPS), ()),
        )

    def std_map(self, header: int) -> list[int]:
        """The nodes of an MSVC `std::map`, in key order - the engine's increment, in Python."""
        out: list[int] = []
        node = self.pointer(header + _MAP_LEFT)
        while node is not None and node != header and self.spend():
            out.append(node)
            right = self.pointer(node + _MAP_RIGHT)
            if right is not None:
                node = right
                while (left := self.pointer(node + _MAP_LEFT)) is not None:
                    node = left
                    if not self.spend():
                        return out
                continue
            parent = self.pointer(node + _MAP_PARENT)
            while parent is not None and node == self.pointer(parent + _MAP_RIGHT):
                node = parent
                parent = self.pointer(parent + _MAP_PARENT)
                if not self.spend():
                    return out
            if parent is None:
                break
            if self.pointer(node + _MAP_RIGHT) != parent:
                node = parent
        return out


def read_script_tree(read: Read) -> ScriptTree | None:
    """Every side's script tree, or None when no sides list is loaded (the menu, a teardown)."""
    r = _Reader(read)
    sides_list = r.pointer(THE_SIDES_LIST)
    if sides_list is None:
        return None
    count = r.i32(sides_list + SIDES_LIST_SIDE_COUNT)
    if count is None or not (0 <= count <= _MAX_SIDES):
        return None
    sides = tuple(
        r.side(i, sides_list + SIDES_LIST_SIDES + i * SIDES_INFO_STRIDE + SIDES_INFO_SCRIPT_LIST)
        for i in range(count)
    )
    engine = r.pointer(THE_SCRIPT_ENGINE)
    difficulty = r.i32(engine + SCRIPT_ENGINE_DIFFICULTY) if engine is not None else None
    return ScriptTree(sides=sides, difficulty=difficulty)


def read_script_variables(read: Read) -> list[ScriptVariable]:
    """Every counter, timer and flag, counters and timers first, each map in key order."""
    r = _Reader(read)
    engine = r.pointer(THE_SCRIPT_ENGINE)
    if engine is None:
        return []
    out: list[ScriptVariable] = []
    for map_offset, is_flag in ((SCRIPT_ENGINE_COUNTER_MAP, False), (SCRIPT_ENGINE_FLAG_MAP, True)):
        header = r.pointer(engine + map_offset)
        if header is None:
            continue
        for node in r.std_map(header):
            record = node + STD_MAP_NODE_VALUE
            if is_flag:
                kind, value, seconds = "flag", int(r.flag(record)), False
            else:
                timer = r.flag(record + SCRIPT_COUNTER_IS_TIMER)
                kind = "timer" if timer else "counter"
                value = r.i32(record + SCRIPT_COUNTER_VALUE) or 0
                seconds = r.flag(record + SCRIPT_COUNTER_IS_SECONDS)
            out.append(
                ScriptVariable(
                    kind=kind,
                    scope=r.ascii(node + _MAP_KEY_SCOPE),
                    name=r.ascii(node + _MAP_KEY_NAME),
                    value=value,
                    seconds=seconds,
                    address=record,
                )
            )
    return out
