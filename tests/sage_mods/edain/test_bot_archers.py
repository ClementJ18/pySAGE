"""Pulling archers out of melee, which is the one corner of the counter triangle the ini cannot
state.

Swords beat pikes, pikes beat cavalry and cavalry beats swords - all three are numbers in the
tree, and `Statics.effectiveness` reads them. "Archers beat everything until something reaches
them" is not: effectiveness answers **0.82** for Gondor archers into cavalry, because an archer's
advantage is not a damage multiplier, it is not being in contact. So the rule is positional and
has to be written.

The clause that matters most here is the one that does *nothing*: running from something faster
means dying strung out and not shooting, which is worse than turning to fight.

**The stage is currently unwired from `Bot.decide`** - see the note there. It fired 202 times in
a measured match and about half were withdrawals from armed support that was not attacking, so
the trigger wants to be damage taken rather than proximity. These tests keep covering it so the
rule is ready when that lands.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.tuning import ARCHER, ARCHER_CONTACT
from sage_mods.edain.bot.warfare import Warfare

FOOT, HORSE = 55.0, 120.0
ARCHERS, SWORDS, KNIGHTS = "GondorArcherHorde", "GondorFighterHorde", "IsengardWargRiderHorde"
SPEEDS = {ARCHERS: FOOT, SWORDS: FOOT, KNIGHTS: HORSE}


def _unit(object_id: int, template: str, x: float) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        position=(x, 0.0, 0.0),
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


class Line(Warfare):
    """`stage_archers` over a fixed army and a fixed set of hostiles."""

    def __init__(self, mine: list, enemies: list, selectable: bool = True) -> None:
        self._mine = mine
        self._enemies = enemies
        self._selectable = selectable
        self.moves: list = []
        self.statics = SimpleNamespace(speed=lambda t: SPEEDS.get(t, 0.0))
        self.session = SimpleNamespace(move=self._move)

    @property
    def observation(self) -> SimpleNamespace:
        return SimpleNamespace(objects=[*self._mine, *self._enemies], mine=self._mine)

    def army(self) -> list:
        return self._mine

    def role(self, obj, *flags) -> bool:
        return ARCHER in flags and obj.template_name == ARCHERS

    def hostile(self, obj) -> bool:
        return obj in self._enemies

    def select(self, force) -> bool:
        return self._selectable

    def _move(self, point):
        self.moves.append(point)
        return True

    def manoeuvre(self, label, act, units) -> bool:
        act()
        return True


def test_archers_in_contact_fall_back_to_the_melee_line() -> None:
    """The rule. Infantry has reached the bowmen, and there are swordsmen to stand behind."""
    archers, swords = _unit(1, ARCHERS, 1000.0), _unit(2, SWORDS, 500.0)
    line = Line([archers, swords], [_unit(9, SWORDS, 1000.0 + ARCHER_CONTACT / 2)])
    said = line.stage_archers()
    assert said is not None and line.moves
    assert line.moves[0][0] < archers.position[0], "the withdrawal must be toward the melee"


def test_archers_shooting_from_range_are_left_alone() -> None:
    """An archer trading arrows across a field is doing its job. `ARCHER_CONTACT` is the whole
    of the distinction, and pulling this one back would end the only thing it is good at."""
    archers, swords = _unit(1, ARCHERS, 1000.0), _unit(2, SWORDS, 500.0)
    line = Line([archers, swords], [_unit(9, SWORDS, 1000.0 + ARCHER_CONTACT * 3)])
    assert line.stage_archers() is None
    assert not line.moves


def test_archers_caught_by_cavalry_stand_and_fight() -> None:
    """The clause that does nothing, and the reason it is in the rule. Foot is 55 and cavalry
    120: running means taking the same melee anyway, strung out in a line and not shooting."""
    archers, swords = _unit(1, ARCHERS, 1000.0), _unit(2, SWORDS, 500.0)
    line = Line([archers, swords], [_unit(9, KNIGHTS, 1000.0 + ARCHER_CONTACT / 2)])
    assert line.stage_archers() is None
    assert not line.moves


def test_an_unreadable_speed_does_not_move_anyone() -> None:
    """The safe direction: not retreating is what the bot has always done, so a template with no
    readable locomotor keeps that rather than guessing."""
    archers, swords = _unit(1, ARCHERS, 1000.0), _unit(2, SWORDS, 500.0)
    line = Line([archers, swords], [_unit(9, "SomeModUnit", 1000.0 + ARCHER_CONTACT / 2)])
    assert line.stage_archers() is None


def test_an_army_of_only_archers_has_nowhere_to_fall_back_to() -> None:
    """A line of bowmen with nothing in front of it is not helped by walking backwards."""
    archers = _unit(1, ARCHERS, 1000.0)
    line = Line([archers], [_unit(9, SWORDS, 1000.0 + ARCHER_CONTACT / 2)])
    assert line.stage_archers() is None
    assert not line.moves


def test_a_failed_selection_moves_nobody() -> None:
    """Every order here acts on the selection, so a move issued unselected walks whatever the
    last stage happened to have picked."""
    archers, swords = _unit(1, ARCHERS, 1000.0), _unit(2, SWORDS, 500.0)
    line = Line(
        [archers, swords], [_unit(9, SWORDS, 1000.0 + ARCHER_CONTACT / 2)], selectable=False
    )
    assert line.stage_archers() is None
    assert not line.moves


def test_a_seat_with_no_archers_does_nothing() -> None:
    """Most factions field some, but a force that has none must cost one comparison."""
    line = Line([_unit(1, SWORDS, 1000.0)], [_unit(9, SWORDS, 1000.0)])
    assert line.stage_archers() is None
