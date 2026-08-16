"""Why the nests are remembered rather than re-read, and what that buys the rebuild hole.

`World.nests` read the live observation and nothing else, so a lair was a target only on the
cycles something of ours happened to be looking at one. Measured live over a single run: the
`nests` column read 21 at cycle 4, 2 at cycle 14, and 0 for most of the rest of a match on a map
still covered in lairs. Twenty-one nests were not destroyed in ten cycles.

The rebuild hole is what turns that from a limitation into a loop that cannot be broken. A hole
exists only once its lair is down - the one moment the force is standing on top of it - and
`RebuildHoleBehavior` raises the lair again two minutes later. Read live, the hole left the
target list with the party that made it, so razing a lair bought two minutes and nothing else.

The boundary tests are therefore: the memory survives the fog, it is not fooled into forgetting
by distance, it *does* forget once the army is standing there, and the hole that replaces a
razed lair is picked up on the cycle the lair goes.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.world import World

CREEPS = 9
MINE = 1
LAIR = "SpiderLair"
HOLE = "SpiderLairHole"


def _at(x: float) -> SimpleNamespace:
    """Something of ours standing at `x`, for the forgetting rule to measure against."""
    return SimpleNamespace(distance_to=lambda other, x=x: abs(other[0] - x))


def _nest(
    object_id: int, template: str = LAIR, x: float = 0.0, owner: int | None = CREEPS
) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        owner_index=owner,
        template_name=template,
        has_body=True,
        position=(x, 0.0, 0.0),
        distance_to=lambda other, x=x: abs(other[0] - x),
    )


class Board:
    """`nests` and its memory over a fogged view, with the army placed by hand."""

    nests = World.nests
    nests_visible = World.nests_visible
    remember_nests = World.remember_nests

    def __init__(self, seen: list, army: list | None = None) -> None:
        self._seen_nests = {}
        self._army = army or []
        self.observation = SimpleNamespace(objects=tuple(seen))
        self.session = SimpleNamespace(player_index=MINE)
        self.statics = SimpleNamespace(
            has_kind=lambda name, *kinds: False,
            is_rebuild_hole=lambda name: name.endswith("Hole"),
        )

    def army(self) -> list:
        return self._army

    def is_lair(self, obj: SimpleNamespace) -> bool:
        return obj.template_name == LAIR

    def look(self, seen: list) -> None:
        """A cycle: the seat sees `seen`, and the memory is written from it."""
        self.observation = SimpleNamespace(objects=tuple(seen))
        self.remember_nests()


def test_a_nest_seen_once_stays_a_target_through_the_fog() -> None:
    """The bug, at its simplest. The opening sees the map; a cycle later it sees none of it."""
    board = Board(seen=[])
    board.look([_nest(1), _nest(2), _nest(3)])
    assert len(board.nests()) == 3

    board.look([])
    assert sorted(o.object_id for o in board.nests()) == [1, 2, 3]


def test_distance_alone_never_forgets_a_nest() -> None:
    """Absence from the fogged view is ordinarily just distance. Forgetting on it is how the
    list emptied itself: the army turns round, and the map it crossed goes back to being empty."""
    board = Board(seen=[], army=[_at(5000.0)])
    board.look([_nest(1)])
    board.look([])
    assert [o.object_id for o in board.nests()] == [1]


def test_a_nest_the_army_is_standing_on_and_cannot_see_is_gone() -> None:
    """The other half of the rule. Within `PUSH_ARRIVED` the absence means the opposite - we are
    on top of the place and it is not there - which is what retires a nest that has been razed."""
    board = Board(seen=[], army=[_at(0.0)])
    board.look([_nest(1, x=0.0)])
    board.look([])
    assert board.nests() == []


def test_walking_past_a_fogged_nest_does_not_delete_it() -> None:
    """**The regression that undid the whole memory, and it was a radius.** Forgetting first
    reused `PUSH_ARRIVED`, which is 400 and wider than a unit's vision - so a battalion crossing
    the map at 350 from a fogged lair deleted it. Measured live over two runs, the `nests` column
    fell 2 -> 0 and 4 -> 1 on maps where nothing had been destroyed, and a lair hole was left
    undestroyed because it had been forgotten rather than given up on.

    A keep survives that rule because the push walks onto it; a hole is a stump."""
    board = Board(seen=[], army=[_at(350.0)])
    board.look([_nest(1, x=0.0)])
    board.look([])
    assert [o.object_id for o in board.nests()] == [1]


def test_the_hole_replaces_the_lair_on_the_cycle_the_lair_dies() -> None:
    """The case the memory exists for. The party that razes a lair is by definition standing on
    it, so the lair is forgotten and the hole - a new object at the same spot - is remembered in
    the same breath. Read live, the hole left with the party and the lair came back."""
    board = Board(seen=[], army=[_at(0.0)])
    board.look([_nest(1, LAIR, x=0.0)])

    # The lair goes down; `RebuildHoleExposeDie` puts the stump in its place.
    board.look([_nest(2, HOLE, x=0.0)])
    assert [(o.object_id, o.template_name) for o in board.nests()] == [(2, HOLE)]

    # And the party walks away. The hole must still be a target, or the lair simply returns.
    board._army = [_at(5000.0)]
    board.look([])
    assert [o.object_id for o in board.nests()] == [2]


def test_the_memory_carries_the_freshest_reading_of_a_nest() -> None:
    """A remembered nest is refreshed while it is in sight, so its position is never staler than
    the last look at it - the same arrangement `plots_now` makes for a plot."""
    board = Board(seen=[])
    board.look([_nest(1, x=100.0)])
    board.look([_nest(1, x=100.0)])
    assert board.nests()[0].position == (100.0, 0.0, 0.0)


def test_an_army_that_does_not_exist_yet_forgets_nothing() -> None:
    """The opening reads the map before it has anything to walk it with, and a memory that
    emptied itself there would start the match blind."""
    board = Board(seen=[], army=[])
    board.look([_nest(1)])
    board.look([])
    assert [o.object_id for o in board.nests()] == [1]
