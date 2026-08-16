"""Crates, and why collecting one is a move order rather than anything aimed at it.

A crate is picked up by colliding with it - `SalvageCrateCollide` - and carries
`NOT_AUTOACQUIRABLE` and `UNATTACKABLE` besides, so no army collects one by fighting nearby and
no attack order means anything against it. Nothing in the bot referenced `CRATE` at all, which
means every treasure chest, experience chest, palantír shard and dropped Ring on every map was
walked past for the whole of every match.

The rule that shapes the stage is the crate's own clock: `DeletionUpdate` gives it thirty to
thirty-five seconds, against an engine running at roughly a fifth of its nominal rate. So a
battalion fetched from across the map arrives at bare ground having abandoned what it was doing,
and `CRATE_REACH` is the distance at which collecting one is still a detour rather than a trip.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from sage_mods.edain.bot.tuning import CRATE, CRATE_REACH, CRATE_REORDER
from sage_mods.edain.bot.warfare import Warfare
from sage_mods.edain.bot.world import World

CHEST = "TreasureChest50"
SWORD = "GondorFighterHorde"


def _thing(object_id: int, template: str, x: float) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        position=(x, 0.0, 0.0),
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


class Map:
    """`crates` and `stage_crate` over a board placed by hand."""

    crates = World.crates
    stage_crate = Warfare.stage_crate

    def __init__(
        self,
        objects: list,
        army: list,
        forming: tuple[int, ...] = (),
        parties: dict | None = None,
        selects: bool = True,
        moves: bool = True,
    ) -> None:
        self._army = army
        self._forming = forming
        self._parties = parties or {}
        self._crate_at: dict[int, float] = {}
        self._selects = selects
        self._moves = moves
        self.moved: list[tuple] = []
        self.observation = SimpleNamespace(objects=objects)
        self.statics = SimpleNamespace(
            has_kind=lambda name, *kinds: CRATE in kinds and "Chest" in name
        )
        self.session = SimpleNamespace(move=self._move)

    def base_centre(self) -> tuple[float, float, float]:
        return (0.0, 0.0, 0.0)

    def army(self) -> list:
        return self._army

    def select(self, units) -> bool:
        return self._selects

    def _move(self, position):
        self.moved.append(position)
        return self._moves

    def manoeuvre(self, label, act, units) -> bool:
        return bool(act()) and self._moves


def test_a_crate_is_found_by_its_flag_rather_than_its_name() -> None:
    """Fifteen crate templates ship in `crate.ini` and a mod may add a sixteenth. The flag covers
    all of them; a name list covers whichever ones somebody remembered."""
    board = Map([_thing(1, CHEST, 100.0), _thing(2, SWORD, 100.0)], army=[])
    assert [o.object_id for o in board.crates()] == [1]


def test_an_idle_battalion_is_sent_to_walk_over_the_crate() -> None:
    """The whole stage. `_forming` is the only place a battalion ever idles, so it is the one
    pool from which taking a body costs nothing."""
    unit = _thing(9, SWORD, 50.0)
    board = Map([_thing(1, CHEST, 100.0)], army=[unit], forming=(9,))
    said = board.stage_crate()
    assert board.moved == [(100.0, 0.0, 0.0)]
    assert said is not None and CHEST in said


def test_a_crate_beyond_reach_is_left_alone() -> None:
    """**Set by the crate's own timer.** It is gone in about half a minute, so a battalion sent
    from across the map abandons its job and arrives at nothing."""
    unit = _thing(9, SWORD, 0.0)
    board = Map([_thing(1, CHEST, CRATE_REACH * 3)], army=[unit], forming=(9,))
    assert board.stage_crate() is None
    assert board.moved == []


def test_a_party_battalion_is_used_only_when_nothing_is_idle() -> None:
    """Taking one off a party is taking it off a flag it is walking to, so the idle pool goes
    first and this is the fallback."""
    unit = _thing(9, SWORD, 50.0)
    board = Map([_thing(1, CHEST, 100.0)], army=[unit], parties={0: (9,)})
    board.stage_crate()
    assert board.moved == [(100.0, 0.0, 0.0)]


def test_the_same_battalion_is_not_re_aimed_every_cycle() -> None:
    """Every re-issue restarts the path, which is how a unit takes one step per cycle and never
    arrives. The latch is short because the crate expires, but it is not zero."""
    unit = _thing(9, SWORD, 50.0)
    board = Map([_thing(1, CHEST, 100.0)], army=[unit], forming=(9,))
    board.stage_crate()
    assert len(board.moved) == 1

    assert board.stage_crate() is None
    assert len(board.moved) == 1

    # Once the latch has aged out the same battalion may be aimed again.
    board._crate_at[9] = time.monotonic() - CRATE_REORDER - 1.0
    board.stage_crate()
    assert len(board.moved) == 2


def test_an_empty_map_asks_for_nothing() -> None:
    """The ordinary case for most of a match, and it must cost one list comprehension."""
    board = Map([_thing(2, SWORD, 10.0)], army=[_thing(9, SWORD, 0.0)], forming=(9,))
    assert board.stage_crate() is None


def test_a_crate_with_no_army_to_fetch_it_is_not_an_error() -> None:
    """The opening before anything is recruited, and every cycle after a wipe."""
    board = Map([_thing(1, CHEST, 100.0)], army=[])
    assert board.stage_crate() is None
