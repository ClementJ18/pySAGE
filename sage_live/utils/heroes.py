"""The revive system: how a hero is recruited, and which building may recruit it.

A hero is recruited by its **position in the player's revive list**, not by template id: the same
`QUEUE_UNIT_CREATE` order as a unit, with the leading flag set. The list starts as the player's
`BuildableHeroesMP` roster (0-based, `CreateAHero` first), and a hero that has been fielded leaves
it, so the ones behind it move up (`current_list`).

Heroes bind to a building's `Command = REVIVE` buttons by position, offset by one: `roster_index =
position - 1`, because position 0 is the Ring-hero slot. A building carries the whole slot block and
disables the slots it must not offer with an unobtainable `NeededUpgrade`.

The derivation, the live confirmations and the known exceptions are in
`sage_patch/docs/hero-recruitment.md`.
"""

from __future__ import annotations

from collections.abc import Container, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "ReviveLookup",
    "ReviveSlot",
    "current_list",
    "revive_index",
]


@dataclass(frozen=True)
class ReviveSlot:
    """One `Command = REVIVE` button of a producer's `CommandSet`.

    `position` counts REVIVE buttons only, in slot order, including ones hidden by an unmet
    `NeededUpgrade` - the same count `BuildAssistant::canMakeUnit` uses.
    """

    position: int
    command_slot: int
    button: str
    needed_upgrades: tuple[str, ...] = ()
    hide_while_disabled: bool = True

    @property
    def roster_index(self) -> int:
        """The `BuildableHeroesMP` index this slot serves - the number an order carries.

        Negative for position 0, the Ring-hero slot, which serves no roster entry.
        """
        return self.position - 1

    @property
    def is_ring_hero(self) -> bool:
        return self.position == 0

    def enabled_for(self, upgrades: Container[str]) -> bool:
        """Whether this button's `NeededUpgrade` requirement is met by `upgrades`.

        `upgrades` is lowercased and is the union of the player's and the building's own. Several
        entries are read as *any of* (one button lists nine mutually exclusive AI-difficulty
        upgrades).
        """
        if not self.needed_upgrades:
            return True
        return any(u.lower() in upgrades for u in self.needed_upgrades)


class ReviveLookup(Protocol):
    """The two static facts the revive system needs, as a protocol so `Session` imports nothing from
    `sage_ini`. `sage_live.utils.statics.Statics` satisfies it.
    """

    def hero_roster(self, faction: str) -> tuple[str, ...]: ...

    def revive_slots(self, template: str) -> tuple[ReviveSlot, ...]: ...


def current_list(
    roster: Sequence[str],
    fielded: Iterable[str] = (),
    dead: Sequence[str] = (),
) -> tuple[str, ...]:
    """The player's revive list as it stands, given what the map shows.

    - a hero **on the map** has left the list, and everything behind it moved up;
    - a hero **killed after fielding** re-enters at the tail, in death order;
    - a hero **in production** still holds its position.

    `fielded` is the hero templates currently owned; `dead` is those seen alive earlier and gone
    now, which only `Session` can accumulate across frames.
    """
    alive = {t.lower() for t in fielded}
    gone = [d.lower() for d in dead]
    remaining = [h for h in roster if h.lower() not in alive and h.lower() not in gone]
    by_key = {h.lower(): h for h in roster}
    return (*remaining, *(by_key[d] for d in gone if d in by_key))


def revive_index(
    roster: Sequence[str],
    hero: str,
    fielded: Iterable[str] = (),
    dead: Sequence[str] = (),
) -> int | None:
    """`hero`'s current position in the revive list, or None when it is not recruitable now (for
    example, because it is on the map).
    """
    key = hero.lower()
    for index, name in enumerate(current_list(roster, fielded, dead)):
        if name.lower() == key:
            return index
    return None
