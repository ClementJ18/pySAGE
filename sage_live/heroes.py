"""The revive system: how a hero is recruited, and which building may recruit it.

**A hero is not recruited by template id.** `recruit` queues a unit by naming its
`ThingTemplate`; a hero is queued by naming its **position in the player's revive list**,
and the two share an order type (`QUEUE_UNIT_CREATE`, `0x417`) distinguished only by the
leading boolean. That is why `orders.recruit`'s flag=True form produced heroes nobody asked
for: it was being fed a `CommandSet` slot number, and the engine reads a revive index.

**The index space is the player's `BuildableHeroesMP` roster**, 0-based, with `CreateAHero`
at position 0. Confirmed against two live recruits on RotWK 2.01 + Edain:

| order arg | building | roster entry | what appeared |
|---|---|---|---|
| 7 | `GondorBarracks` | `FactionMen[7]` = `GondorImrahil` | Imrahil |
| 1 | `LothlorienCastleBaseKeep` | `FactionElves[1]` = `LothlorienRumil` | Rumil + Orophin |

`LothlorienRumil` fields a pair - Haldir's brothers share one roster entry - which is why
the second recruit was first recorded as "the hero Orophin".

**Heroes attach to `Command = REVIVE` buttons by position.** A building that recruits any
hero carries the whole slot block, and the slots it must not offer are disabled with a
`NeededUpgrade` the building can never hold. `GondorBarracksCommandSet` carries 14 REVIVE
buttons of which exactly two are ungated, and those two are the barracks' real heroes.

The binding is positional, offset by one: **`roster_index = position - 1`**, because
position 0 is the Ring-hero slot and the Ring hero is not a roster entry. Worked through on
the Gondor barracks, whose two ungated slots sit at positions 3 and 5:

| position | button | roster index | hero |
|---|---|---|---|
| 0 | `Command_FakeRingHeroReviveSlot` | - | the Ring hero |
| 1 | `Command_FakeCreateAHeroReviveSlot` | 0 | `CreateAHero` |
| 3 | `Command_GenericReviveSlot2` | 2 | `GondorBeregond` |
| 5 | `Command_GenericReviveSlot4` | 4 | `GondorBoromir_mod` |

Beregond and Boromir are exactly the heroes an Edain Gondor barracks offers, which is the
corroboration that the offset is right rather than merely self-consistent.

**Measured over the whole RotWK 2.01 + Edain tree.** Many revive buttons are named after the
hero they recruit (`Command_HaldirGenericReviveSlot`), which is an author's statement of the
binding and independent of the position it sits at. **220 of 231 such buttons land on their own
roster entry** under the rule above - including four in a row at the Lothlorien keep, where
Rumil, Haldir, Celeborn and Galadriel each sit at the position serving their own entry.

Six of the eleven exceptions are not exceptions: `Command_HaldirsBruderGenericReviveSlot` is
Haldir's *brother*, Rumil, and lands correctly. Two are permanently-gated fillers whose names
never mattered. The two that remain are on `RohanCitadel`, whose block also carries an enabled
slot serving entry 12 of an eight-entry roster - a set that does not line up, most likely stale
naming from an older roster. `Statics.check_revive_slots` reports that shape; 9 of the tree's
187 playable-faction producers trip it.

Do not read the *numbers* in these button names as roster indices, tempting as it is:
`Command_GenericReviveSlot1` occurs at positions 0, 1, 3 and 4 in different sets, so its number
identifies the button and not a hero.

**What is not derived here.** The engine builds its own button-to-hero mapping in a separate
ControlBar walk (`0x00943F81`) that has not been disassembled, so the offset above is inferred
from the data and two live samples rather than read out of the binary. Where the ControlBar and
the gate disagree the stock engine cannot tell, because `BuildAssistant::canMakeUnit` never
reads the button it matched - see `sage_patch/patches/ai_revive_gate.py`.

**The list is not the roster.** A hero that has been fielded leaves the list and everything
behind it slides forward, so a roster position is only a revive index while nobody has been
recruited yet. `current_list` applies that, driven by what an observation can actually see.
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

    `position` counts REVIVE buttons only, in `CommandSet` slot order, and counts them all -
    a button hidden by an unmet `NeededUpgrade` still holds its place. That is what makes the
    mapping stable as upgrades are bought, and it is also what `BuildAssistant::canMakeUnit`
    counts.
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

        `upgrades` must be lowercased, and must be the union of the **player's** completed
        upgrades and the **building's own** - the two scopes are separate fields on a live
        observation and a revive slot may be gated by either.

        A multi-entry `NeededUpgrade` is read as *any of*, which is what the data supports:
        one button in this tree lists nine mutually exclusive AI-difficulty upgrades, and
        an all-of reading would make it permanently dead.
        """
        if not self.needed_upgrades:
            return True
        return any(u.lower() in upgrades for u in self.needed_upgrades)


class ReviveLookup(Protocol):
    """The two static facts the revive system needs, in one injectable surface.

    A protocol rather than a class so `Session` keeps importing nothing from `sage_ini`:
    `sage_live.statics.Statics` satisfies it off an ini load, and a test can satisfy it with
    a literal.
    """

    def hero_roster(self, faction: str) -> tuple[str, ...]: ...

    def revive_slots(self, template: str) -> tuple[ReviveSlot, ...]: ...


def current_list(
    roster: Sequence[str],
    fielded: Iterable[str] = (),
    dead: Sequence[str] = (),
) -> tuple[str, ...]:
    """The player's revive list as it stands, given what the map shows.

    Three rules, taken from the order stream's own behaviour (`sage_replay.heroes`):

    - a hero **on the map** has left the list, and everything behind it slid forward;
    - a hero **killed after fielding** re-enters at the tail, in death order;
    - a hero **in production** still holds its position, which is why this keys off what is
      standing on the map rather than off what has been ordered.

    Everything here is observable: `fielded` is the hero templates currently owned, and `dead`
    is those seen alive earlier and no longer present. The tail is the one part a single
    observation cannot reconstruct - `Session` accumulates it across frames.
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
    """`hero`'s current position in the revive list, or None if it is not in it.

    None means "not recruitable right now", which is a real answer: a hero already on the map
    is not in the list at all, and ordering its old position would recruit whoever slid into
    that place.
    """
    key = hero.lower()
    for index, name in enumerate(current_list(roster, fielded, dead)):
        if name.lower() == key:
            return index
    return None
