"""Driving a scenario's scripts in the running game: fire a trigger, wait for it, read a probe.

The scripts are the ones `sage_test.script_compile` wrote. Everything here is a memory read or a
plain byte write - no code is patched and nothing is hooked - so it works whatever else owns the
game's frame loop, the accelerator included:

- **fire** writes the script's next-evaluation frame to 0 and its live active flag to 1. The
  engine evaluates it on its next pass, runs its actions when the conditions hold, and clears
  the flag itself, since every trigger is one-shot. Firing again re-arms it the same way.
- **the receipt** is the counter `sage_test.<name>` that the script's last action raises.
  `wait_fired` waits for it to pass the value `fire` saw, so it is the one sync point a test
  needs, at any game speed.

Writing a script's state changes what the simulation does, so a network game is refused.

The tree's addresses do not move once the map is loaded, so the tree is read once and kept; each
call then reads only the fields it needs.
"""

from __future__ import annotations

import struct
import time
from typing import Protocol

from sage_live.backends.scripts import (
    LiveScript,
    ScriptVariable,
    read_script_tree,
    read_script_variables,
)
from sage_patch.addresses import (
    GAME_LOGIC_FRAME,
    GAME_LOGIC_GAME_MODE,
    NETWORK_GAME_MODES,
    SCRIPT_ACTIVE,
    SCRIPT_NEXT_FRAME,
    THE_GAME_LOGIC,
)
from sage_test.script_compile import GROUP, counter_name, script_name

__all__ = ["Memory", "ScriptControl", "ScriptError"]

DEFAULT_TIMEOUT = 10.0
POLL = 0.05


class Memory(Protocol):
    def read(self, address: int, size: int) -> bytes | None: ...

    def write(self, address: int, data: bytes) -> bool: ...


class ScriptError(RuntimeError):
    """A scenario script that is not in the game, or did not run when asked."""


class ScriptControl:
    """The scenario scripts of one running game."""

    def __init__(self, memory: Memory) -> None:
        self.memory = memory
        self._found: dict[str, tuple[int, LiveScript]] = {}

    def _u32(self, address: int) -> int | None:
        raw = self.memory.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def frame(self) -> int | None:
        """The current logic frame, or None outside a match."""
        logic = self._u32(THE_GAME_LOGIC)
        return self._u32(logic + GAME_LOGIC_FRAME) if logic else None

    def _refuse_network(self) -> None:
        logic = self._u32(THE_GAME_LOGIC)
        mode = self._u32(logic + GAME_LOGIC_GAME_MODE) if logic else None
        if mode in NETWORK_GAME_MODES:
            raise ScriptError(
                f"this is a network game (mode {mode}); its scripts are not ours to set"
            )

    def _ours(self) -> dict[str, tuple[int, LiveScript]]:
        tree = read_script_tree(self.memory.read)
        if tree is None:
            raise ScriptError("no map is loaded")
        return {
            script.name: (side.index, script)
            for side in tree.sides
            for script in side.all_scripts()
            if script.path[:1] == (GROUP,)
        }

    def names(self) -> list[str]:
        """The scenario scripts in the game, without their prefix."""
        prefix = len(script_name(""))
        return sorted(name[prefix:] for name in self._ours())

    def find(self, name: str) -> tuple[int, LiveScript]:
        """`(side, script)` for a scenario script, by the name the scenario declared."""
        if name not in self._found:
            ours = self._ours()
            self._found.update({key[len(script_name("")) :]: value for key, value in ours.items()})
            if name not in self._found:
                listed = ", ".join(self.names()) or "none"
                raise ScriptError(
                    f"script {name!r} is not in the game (scenario scripts: {listed})"
                )
        return self._found[name]

    def active(self, name: str) -> bool:
        _, script = self.find(name)
        raw = self.memory.read(script.address + SCRIPT_ACTIVE, 1)
        if raw is None:
            raise ScriptError(f"script {name!r} is unreadable - the game exited?")
        return bool(raw[0])

    def _set_active(self, name: str, on: bool) -> None:
        self._refuse_network()
        _, script = self.find(name)
        if on and not self.memory.write(script.address + SCRIPT_NEXT_FRAME, struct.pack("<I", 0)):
            raise ScriptError(f"re-arming {name!r} failed")
        if not self.memory.write(script.address + SCRIPT_ACTIVE, b"\x01" if on else b"\x00"):
            raise ScriptError(f"switching {name!r} {'on' if on else 'off'} failed")

    def enable(self, name: str) -> None:
        """Switch a script on, due at once. A probe that was switched off counts again."""
        self._set_active(name, True)

    def disable(self, name: str) -> None:
        self._set_active(name, False)

    def variables(self) -> list[ScriptVariable]:
        return read_script_variables(self.memory.read)

    def _variable(self, name: str, kinds: tuple[str, ...]) -> ScriptVariable | None:
        found = [v for v in self.variables() if v.name == name and v.kind in kinds]
        return max(found, key=lambda v: v.value) if found else None

    def count(self, name: str) -> int:
        """How many times a scenario script has run: 0 until its counter exists."""
        variable = self._variable(counter_name(name), ("counter",))
        return variable.value if variable is not None else 0

    def fire(self, name: str) -> int:
        """Switch a trigger on so it runs on the engine's next pass; returns the count before."""
        before = self.count(name)
        self.enable(name)
        return before

    def wait_fired(
        self, name: str, after: int | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> int:
        """Block until the script's count passes `after` (the count now, by default)."""
        start = self.count(name) if after is None else after
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            now = self.count(name)
            if now > start:
                return now
            time.sleep(POLL)
        side, script = self.find(name)
        raw = self.memory.read(script.address + SCRIPT_NEXT_FRAME, 4)
        next_frame = struct.unpack("<I", raw)[0] if raw else None
        raise ScriptError(
            f"script {name!r} (side {side}) did not run within {timeout:g} s: active "
            f"{self.active(name)}, due at frame {next_frame}, game at frame {self.frame()}. "
            "Still active means its conditions never held; inactive with no count means its "
            "actions stopped before the receipt."
        )

    def run(self, name: str, timeout: float = DEFAULT_TIMEOUT) -> int:
        """Fire a trigger and wait for it; returns its new count."""
        return self.wait_fired(name, after=self.fire(name), timeout=timeout)

    def _write_variable(self, name: str, kinds: tuple[str, ...], data: bytes) -> None:
        self._refuse_network()
        variable = self._variable(name, kinds)
        if variable is None:
            raise ScriptError(
                f"no {' or '.join(kinds)} named {name!r} - a variable exists only once a script "
                "has touched it"
            )
        if not self.memory.write(variable.address, data):
            raise ScriptError(f"writing {name!r} failed")

    def set_counter(self, name: str, value: int) -> None:
        """Overwrite a counter some script has already touched - the way to hand a script a
        number chosen at run time."""
        self._write_variable(name, ("counter", "timer"), struct.pack("<i", value))

    def set_flag(self, name: str, value: bool) -> None:
        self._write_variable(name, ("flag",), b"\x01" if value else b"\x00")
