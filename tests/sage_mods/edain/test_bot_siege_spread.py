"""Why the spare siege engines open a second front instead of queueing behind the first.

A building dies to one ram, and the rest arrive after it is rubble. Siege is the one part of the
army where massing is actively wasteful: the damage is enormous and per-target, so four engines
on one structure spend three engines' worth of it on something already falling over - and they
are the slowest thing on the map, so the walk they wasted is the longest one anybody made.

The constraint pulling the other way is the escort. `RECRUIT_NEVER` records why siege is barred
outside a push at all: eight battering rams once walked to their targets alone and achieved
nothing, because escorting them is a behaviour this bot does not have. The push *is* the escort,
so the split has to stay inside its reach - one engine stays with the army, and a second front is
only opened on a building close enough to be part of the same fight.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.tuning import SIEGE, SIEGE_SPREAD
from sage_mods.edain.bot.warfare import Warfare

RAM = "GondorBatteringRam"
SWORD = "GondorFighterHorde"


def _obj(object_id: int, template: str, x: float) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        position=(x, 0.0, 0.0),
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


class Push:
    """`spread_siege` over a force and a set of enemy buildings placed by hand."""

    spread_siege = Warfare.spread_siege

    def __init__(self, structures: list) -> None:
        self._structures = structures

    def role(self, obj: SimpleNamespace, which: str) -> bool:
        return which == SIEGE and obj.template_name == RAM

    def enemy_structures(self) -> list:
        return self._structures


def _pairs(spread: list) -> list[tuple[int, int]]:
    return [(engines[0].object_id, aim.object_id) for engines, aim in spread]


def test_the_spare_engines_go_at_other_buildings() -> None:
    """The point of the change. Three rams, three buildings, three demolitions at once."""
    primary = _obj(100, "IsengardTavern", 0.0)
    push = Push([primary, _obj(101, "IsengardUrukPit", 200.0), _obj(102, "IsengardForge", 300.0)])
    force = [_obj(1, RAM, 0.0), _obj(2, RAM, 0.0), _obj(3, RAM, 0.0), _obj(9, SWORD, 0.0)]
    assert _pairs(push.spread_siege(force, primary)) == [(2, 101), (3, 102)]


def test_one_engine_always_stays_with_the_push() -> None:
    """**Not a compromise - the escort is the whole reason siege is buildable at all.** A lone
    ram is the failure `RECRUIT_NEVER` records, so only the surplus leaves."""
    primary = _obj(100, "IsengardTavern", 0.0)
    push = Push([primary, _obj(101, "IsengardUrukPit", 200.0)])
    force = [_obj(1, RAM, 0.0), _obj(2, RAM, 0.0)]
    spread = push.spread_siege(force, primary)
    assert _pairs(spread) == [(2, 101)]


def test_a_single_engine_is_never_split_off() -> None:
    """With one ram there is no surplus, and sending it away would leave the push with no siege
    at all while the ram walks somewhere alone."""
    primary = _obj(100, "IsengardTavern", 0.0)
    push = Push([primary, _obj(101, "IsengardUrukPit", 200.0)])
    assert push.spread_siege([_obj(1, RAM, 0.0), _obj(9, SWORD, 0.0)], primary) == []


def test_a_building_beyond_the_escort_is_not_a_second_front() -> None:
    """A structure across the map is a ram on its own again, which is exactly what the ban on
    siege outside a push exists to prevent."""
    primary = _obj(100, "IsengardTavern", 0.0)
    push = Push([primary, _obj(101, "IsengardForge", SIEGE_SPREAD * 3)])
    assert push.spread_siege([_obj(1, RAM, 0.0), _obj(2, RAM, 0.0)], primary) == []


def test_surplus_engines_beyond_the_targets_stay_with_the_push() -> None:
    """Four rams and two other buildings: the extra one is left in the main force rather than
    doubling up on a target that is already falling."""
    primary = _obj(100, "IsengardTavern", 0.0)
    push = Push([primary, _obj(101, "IsengardUrukPit", 200.0)])
    force = [_obj(i, RAM, 0.0) for i in (1, 2, 3, 4)]
    assert _pairs(push.spread_siege(force, primary)) == [(2, 101)]


def test_the_nearest_buildings_are_taken_first() -> None:
    """Nearest the *push*, not nearest home - the escort's reach is what makes a second front
    survivable."""
    primary = _obj(100, "IsengardTavern", 0.0)
    push = Push([primary, _obj(101, "Far", 600.0), _obj(102, "Near", 100.0)])
    force = [_obj(1, RAM, 0.0), _obj(2, RAM, 0.0)]
    assert _pairs(push.spread_siege(force, primary)) == [(2, 102)]


def test_a_force_with_no_siege_asks_for_nothing() -> None:
    """The ordinary case for most of a match, and it must leave `stage_push` untouched."""
    primary = _obj(100, "IsengardTavern", 0.0)
    push = Push([primary, _obj(101, "IsengardUrukPit", 200.0)])
    assert push.spread_siege([_obj(9, SWORD, 0.0)], primary) == []
