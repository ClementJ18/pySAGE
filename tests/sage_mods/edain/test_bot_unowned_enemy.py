"""Enemies whose owner cannot be read, which is what a superweapon's summons are.

An object names its owner by `Team*`, and `_team_owners` inverts each player's *primary* team -
so anything on a script team comes back `owner_index is None`. `hostile` used to exclude those
outright, which read "unresolvable" as "neutral".

Measured live at frame 21697: the `None` bucket held 18 `IsengardFighter`, 15
`IsengardUrukCrossbow`, 7 `IsengardWargRider`, a ballista and their hordes - a whole attacking
force, in CLEAR cells and present in the fogged view, that no decision asking `hostile` could
see. It also held five of our own `CPObject`s, which is why the fallback cannot simply be
"unowned means enemy".
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.world import World

OURS = 3


class Sides:
    """`not_ours` over hand-built objects, with our own Side fixed."""

    not_ours = World.not_ours

    def __init__(self) -> None:
        self.side = "Men"
        self.session = SimpleNamespace(player_index=OURS)


def _obj(owner, side: str = "") -> SimpleNamespace:
    return SimpleNamespace(owner_index=owner, template_side=side)


def test_a_resolved_owner_is_read_directly() -> None:
    sides = Sides()
    assert sides.not_ours(_obj(4, "Isengard")) is True
    assert sides.not_ours(_obj(OURS, "Men")) is False


def test_an_unowned_enemy_battalion_is_hostile_by_its_side() -> None:
    """The crossbow horde that shot a farm down while reading as nobody's."""
    assert Sides().not_ours(_obj(None, "Isengard")) is True


def test_our_own_unowned_objects_stay_ours() -> None:
    """Five `CPObject`s read unresolved in the same snapshot; attacking them would be worse
    than missing the enemy."""
    assert Sides().not_ours(_obj(None, "Men")) is False
    assert Sides().not_ours(_obj(None, "men")) is False


def test_an_unowned_object_with_no_side_is_left_alone() -> None:
    """Blank `Side` is no evidence, and the safe default is not to fight it."""
    assert Sides().not_ours(_obj(None, "")) is False
