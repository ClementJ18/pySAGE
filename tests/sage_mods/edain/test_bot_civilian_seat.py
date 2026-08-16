"""Why the civilian seat is out of `hostile` entirely, and the creeps are not.

Every other exclusion in `hostile` reads a `KindOf`, and that is exactly why they cannot carry
this on their own: an object the ini tree does not define resolves to *no* flags, so `STRUCTURE`,
`IMMOBILE`, `HARMLESS` and the rest all fail open and a map decoration reads as a mobile living
thing. Measured live on an Edain map, the complete list of civilian-owned objects `hostile`
accepted was three `Crow` - whose `KindOf` is spelled out longhand and drops the `INERT` every
other animal inherits from `NATUREUNITS_KINDOF` - and one `Mirkwood_Vinecellar1`, which resolved
to an empty kind set. Four battalions spent ten minutes of a push trying to attack a bird they
could not hit, and the order was refused every cycle without ever being given up on.

`PlyrCreeps` stays hostile, and the split is the whole point: lairs and the slaves they keep
replacing are what a flag has to be cleared of, and the same match had a `WargLair` and its
`NeutralWarg` both on that seat. The civilians own rocks, deer, pillars and wine cellars.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.tuning import CIVILIAN_SEAT
from sage_mods.edain.bot.world import World

CIVILIAN = 1
CREEPS = 2
MINE = 3
THEIRS = 4

SEATS = {
    CIVILIAN: CIVILIAN_SEAT,
    CREEPS: "PlyrCreeps",
    MINE: "Player_1",
    THEIRS: "Player_2",
}

# What the tree says about each template. The two live offenders are in here as they really
# resolve: the crow missing INERT, and the vine cellar with nothing at all.
KINDS = {
    "Crow": {"IGNORED_IN_GUI", "INFANTRY", "NOT_AUTOACQUIRABLE", "PRELOAD"},
    "Mirkwood_Vinecellar1": set(),
    "Boar": {"INFANTRY", "INERT"},
    "NeutralWarg": {"INFANTRY"},
    "IsengardWildman": {"INFANTRY"},
}


def _obj(object_id: int, template: str, owner: int) -> SimpleNamespace:
    return SimpleNamespace(object_id=object_id, template_name=template, owner_index=owner)


class Board:
    """`hostile` and `civilian` over seats and kinds set by hand."""

    hostile = World.hostile
    civilian = World.civilian

    def __init__(self) -> None:
        self.observation = SimpleNamespace(
            player=lambda index: (
                SimpleNamespace(index=index, name=SEATS[index]) if index in SEATS else None
            )
        )
        self.statics = SimpleNamespace(
            has_kind=lambda name, *flags: bool(KINDS.get(name, set()) & set(flags)),
            is_horde_member=lambda name: False,
        )

    def not_ours(self, obj: SimpleNamespace) -> bool:
        return obj.owner_index != MINE


def _live(obj: SimpleNamespace) -> SimpleNamespace:
    obj.has_body = True
    return obj


def test_a_crow_is_no_longer_something_to_fight() -> None:
    """The bug, exactly as it was measured. The crow's own `KindOf` drops `INERT`, so every
    flag-based exclusion passes it through and the seat is the only thing left that knows."""
    assert Board().hostile(_live(_obj(299, "Crow", CIVILIAN))) is False


def test_an_object_the_tree_does_not_define_is_not_a_threat_either() -> None:
    """`Mirkwood_Vinecellar1` resolves to an empty kind set, so `STRUCTURE` and `IMMOBILE` both
    answer no and a wine cellar reads as a mobile living thing. This is why the seat test cannot
    be replaced by adding one more flag to `HARMLESS`."""
    assert Board().hostile(_live(_obj(500, "Mirkwood_Vinecellar1", CIVILIAN))) is False


def test_a_creep_warg_is_still_something_to_fight() -> None:
    """**The half that must not break.** A lair's slaves are what a flag has to be cleared of,
    and they are the creeps' - so excluding the wrong seat would report every garrisoned flag as
    free and march parties into them."""
    assert Board().hostile(_live(_obj(77, "NeutralWarg", CREEPS))) is True


def test_a_real_opponent_is_unaffected() -> None:
    """The seat test must not touch the thing the whole bot is playing against."""
    assert Board().hostile(_live(_obj(88, "IsengardWildman", THEIRS))) is True


def test_wildlife_that_was_already_excluded_stays_excluded() -> None:
    """`HARMLESS` still does its job for every animal that inherits the macro properly; the seat
    test is the backstop for the ones that do not."""
    assert Board().hostile(_live(_obj(42, "Boar", CIVILIAN))) is False


def test_the_seat_is_read_by_name_not_by_index() -> None:
    """Seat indices are per-match and prove nothing; the engine's names are fixtures. Both
    non-playing seats report a `Civilian` faction, so the name is the only discriminator."""
    board = Board()
    assert board.civilian(_obj(1, "Crow", CIVILIAN)) is True
    assert board.civilian(_obj(2, "NeutralWarg", CREEPS)) is False


def test_an_unreadable_seat_is_not_treated_as_civilian() -> None:
    """Failing open here would quietly disarm the bot against a player whose entry cannot be
    read, which is a far worse trade than chasing a bird."""
    board = Board()
    assert board.civilian(_obj(3, "IsengardWildman", 99)) is False
