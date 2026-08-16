"""Why a raiding party expects the hole, instead of rediscovering it.

Razing a lair is half a job. `RebuildHoleExposeDie` puts a `REBUILD_HOLE` stump exactly where the
building stood, and `RebuildHoleBehavior` raises the lair again from it about two minutes later -
so a party that walks away has bought two minutes and nothing else.

`raid_target` could not express that, because the hole is a *new object* competing with every
other nest on the map by distance from home. Measured live, four battalions worked four nests for
a hundred cycles and finished none of them, while the `nests` column oscillated 5-6-7: lairs
rebuilding as fast as they were razed. The commitment therefore has to be to the ground rather
than to the object.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.tuning import RAID_FINISH
from sage_mods.edain.bot.warfare import Warfare

LAIR = "SpiderLair"
HOLE = "SpiderLairHole"


def _nest(object_id: int, template: str, x: float) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        position=(x, 0.0, 0.0),
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


class Raid:
    """`unfinished_nest` over a map whose nests are placed by hand."""

    unfinished_nest = Warfare.unfinished_nest

    def __init__(self, nests: list, spot: tuple | None = None) -> None:
        self._nests = nests
        self._raid_spot = {0: spot} if spot is not None else {}
        self.statics = SimpleNamespace(is_rebuild_hole=lambda name: name.endswith("Hole"))

    def nests(self) -> list:
        return self._nests


def test_the_hole_left_behind_is_the_same_job() -> None:
    """The whole point. The lair is gone, a stump stands where it was with a new id, and the
    party that made it is the party that should finish it."""
    raid = Raid([_nest(2, HOLE, 10.0), _nest(9, LAIR, 5000.0)], spot=(0.0, 0.0, 0.0))
    assert raid.unfinished_nest(0, set()).object_id == 2


def test_a_far_nest_is_not_mistaken_for_the_same_spot() -> None:
    """The commitment is to a building's footprint, not to a region of the map - otherwise one
    raid would swallow every nest in a quarter of it."""
    raid = Raid([_nest(9, LAIR, RAID_FINISH * 4)], spot=(0.0, 0.0, 0.0))
    assert raid.unfinished_nest(0, set()) is None


def test_a_cleared_spot_releases_the_party() -> None:
    """Once the ground is clear the party goes back to `raid_target` for a fresh job, and the
    commitment must not pin it to an empty patch for the rest of the match."""
    raid = Raid([], spot=(0.0, 0.0, 0.0))
    assert raid.unfinished_nest(0, set()) is None
    assert 0 not in raid._raid_spot


def test_the_hole_is_preferred_over_a_lair_at_the_same_spot() -> None:
    """`garrison_of` gives the reason: a hole only exists once its lair is down, and it is the
    cheaper of the two targets."""
    raid = Raid([_nest(1, LAIR, 20.0), _nest(2, HOLE, 30.0)], spot=(0.0, 0.0, 0.0))
    assert raid.unfinished_nest(0, set()).object_id == 2


def test_a_nest_another_party_claimed_is_left_alone() -> None:
    """Two parties on one lair is the massing `stage_raid` splits parties up to avoid."""
    raid = Raid([_nest(2, HOLE, 10.0)], spot=(0.0, 0.0, 0.0))
    assert raid.unfinished_nest(0, {2}) is None


def test_a_party_with_no_commitment_asks_for_nothing() -> None:
    """The ordinary case on the first raid of a match, and it must cost one dict lookup."""
    assert Raid([_nest(2, HOLE, 10.0)]).unfinished_nest(0, set()) is None
