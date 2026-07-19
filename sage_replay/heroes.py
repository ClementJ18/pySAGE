"""Resolve `0x417` flag=True hero-recruit slot ids to hero names.

The slot id is the hero's *current position* in the player's revive submenu, whose state
the order stream plus static game data fully determine (order_space_map.md, `0x417`):

- the list starts as the faction's `BuildableHeroesMP` order, placeholders included
  (CreateAHero is position 0); locked heroes hold their positions;
- a hero *in production* still holds its position;
- a *fielded* hero is removed and everything behind it slides forward - fielding time is
  the recruit's clock plus the hero's revive `BuildTime` (static ini data);
- a hero *killed* after fielding re-enters at the tail of the list;
- a `0x418` flag=True cancel names the same current position and never shifts anyone.

Deaths themselves are invisible in the stream, so a tail position is resolvable only
when a single hero has fielded (then only it can be the re-entrant). With several
candidates the recruit stays unresolved - `recruit` returns None and the list state is
still correct for every in-range position (unknown dead entries sit past the tail).

Ground-truthed by the three `hero recruit*.BfME2Replay` Linhir fixtures.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

__all__ = ["ReviveList"]


class ReviveList:
    """One player's revive submenu, advanced recruit by recruit. `build_times` maps hero
    name -> revive seconds; a hero without an entry never fields (it keeps its position,
    so every position before it still resolves)."""

    def __init__(self, roster: Sequence[str], build_times: Mapping[str, float]) -> None:
        self._entries: list[str] = list(roster)
        self._build_times = dict(build_times)
        self._pending: dict[str, float] = {}  # hero -> seconds at which it fields
        self._fielded: list[str] = []  # fielded and still listed nowhere (a death is unseen)

    def _advance(self, seconds: float) -> None:
        """Field every pending hero whose revive has completed by `seconds`."""
        for name, fields_at in list(self._pending.items()):
            if fields_at <= seconds:
                del self._pending[name]
                if name in self._entries:
                    self._entries.remove(name)
                    self._fielded.append(name)

    def recruit(self, seconds: float, slot: int) -> str | None:
        """The hero recruited at submenu position `slot`, or None when the position is
        unresolvable (past the tail with several possible dead heroes, or no roster)."""
        self._advance(seconds)
        if 0 <= slot < len(self._entries):
            name = self._entries[slot]
        elif slot == len(self._entries) and len(self._fielded) == 1:
            # The tail: a dead hero re-entered. Unambiguous only when a single fielded
            # hero can have died; it rejoins the list at this position.
            name = self._fielded.pop()
            self._entries.append(name)
        else:
            return None
        fields_in = self._build_times.get(name)
        if fields_in is not None:
            self._pending[name] = seconds + fields_in
        return name

    def cancel(self, seconds: float, slot: int) -> str | None:
        """The hero whose queued revive position `slot` cancels; its production is
        un-queued (the hero keeps its position - a cancel never shifts the list)."""
        self._advance(seconds)
        if not 0 <= slot < len(self._entries):
            return None
        name = self._entries[slot]
        self._pending.pop(name, None)
        return name

    def slot_of(self, seconds: float, name: str) -> int | None:
        """The inverse of `recruit`: the submenu position at which recruiting hero `name` at
        `seconds` lands, mutating the list state exactly as the recruit itself would - so a
        stream of known recruits re-emits the slot ids a client under THIS roster would have
        sent (`sage_replay.retarget` drives it with the target game's roster and build times).
        Knowing the name makes the dead-re-entry tail case unambiguous where the forward
        direction is not: a fielded hero re-enters at the tail regardless of how many other
        heroes have fielded. None for a hero this roster never listed."""
        self._advance(seconds)
        if name in self._entries:
            slot = self._entries.index(name)
        elif name in self._fielded:
            slot = len(self._entries)
            self._fielded.remove(name)
            self._entries.append(name)
        else:
            return None
        fields_in = self._build_times.get(name)
        if fields_in is not None:
            self._pending[name] = seconds + fields_in
        return slot

    def cancel_slot_of(self, seconds: float, name: str) -> int | None:
        """The inverse of `cancel`: the position a cancel of hero `name`'s queued revive
        names at `seconds`, un-queuing it (the list never shifts). None for a hero not
        currently listed."""
        self._advance(seconds)
        if name not in self._entries:
            return None
        self._pending.pop(name, None)
        return self._entries.index(name)
