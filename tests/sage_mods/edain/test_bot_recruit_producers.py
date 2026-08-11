"""Not ordering production at a building that has not finished going up.

This one has no refusal in it, which is what made it invisible. A structure under construction
carries its finished `CommandSet`, so it answers `Statics.recruits` with the full palette and then
*accepts* what is ordered against it - the cost is committed and the battalion sits in a queue
that cannot start until the building is up. Nothing in the log says so.

The producer choice then makes it systematic rather than occasional. `next_recruit` spreads orders
by queue depth, `min(usable, key=queued_units)`, and a building that cannot start anything has the
emptiest queue on the map - so the shell outranks every finished building until it is full, and
`held` counts everything stacked on it as already coming.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.recruiting import Recruiting
from sage_mods.edain.bot.world import World

ARCHERS = "GondorArcherHorde"


def _site(
    object_id: int,
    template: str = "GondorArcherRange",
    under_construction: bool = False,
    is_rubble: bool = False,
) -> SimpleNamespace:
    # Both readings are `ModelCondition`s on the live object rather than health thresholds - a
    # structure ramps its hit points as it builds, and wreckage sits at zero wearing `RUBBLE`.
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        under_construction=under_construction,
        is_rubble=is_rubble,
    )


class Yard:
    """`producers` and `next_recruit` over a stub base, with the queue depths dictated."""

    producers = Recruiting.producers
    next_recruit = Recruiting.next_recruit
    production_sites = World.production_sites

    def __init__(self, sites: list, queues: dict[int, int] | None = None) -> None:
        self._sites = sites
        self._queues = queues or {}
        self._pushing = False
        self.army_plan = SimpleNamespace(members=[SimpleNamespace(unit=ARCHERS)])
        self.statics = SimpleNamespace(
            has_kind=lambda template, *flags: False,
            fighting_template=lambda unit: unit,
            recruits=lambda template, held: frozenset({ARCHERS.lower()}),
            build_cost=lambda unit: 200,
        )

    def structures(self) -> list:
        return self._sites

    def held_by(self, obj) -> set[str]:  # noqa: ANN001
        return set()

    def queued_units(self, building) -> int:  # noqa: ANN001
        return self._queues.get(building.object_id, 0)

    def wanted_mix(self) -> dict[str, float]:
        # Taken over `producers` rather than stated flat, because the real one is: it keeps only
        # `member.unit in producers` and `promote` refuses an elite the same way. That subset
        # relation is what makes `producers[unit]` in `next_recruit` a safe lookup, so a stub that
        # broke it would be testing an unreachable path.
        return dict.fromkeys(self.producers(), 1.0)

    def held(self) -> dict[str, int]:
        return {}

    def building_reserve(self) -> int:
        return 0

    def afford(self, unit: str, reserve: int = 0) -> bool:
        return True


def test_a_building_still_going_up_is_not_a_producer() -> None:
    """It sells the full palette while it is a shell, so the pool has to drop it here - there is
    no later gate, because the order it would be given succeeds."""
    yard = Yard([_site(10, under_construction=True)])
    assert yard.producers() == {}
    assert yard.next_recruit() is None


def test_wreckage_is_not_a_producer() -> None:
    """A destroyed building stays in the object table wearing `RUBBLE` - owned, not under
    construction, and selling nothing."""
    yard = Yard([_site(10, is_rubble=True)])
    assert yard.producers() == {}


def test_the_shell_does_not_outrank_a_busy_finished_building() -> None:
    """**The failure this whole gate exists for.** Orders spread by queue depth, so an unfinished
    building - queue necessarily empty - beats a finished one that is merely working, every cycle
    until `QUEUE_TARGET` battalions are stacked behind it and none of them have started. At a
    target of 2 that is the base's whole output for two cycles, paid for and frozen."""
    # One deep, not full: `QUEUE_TARGET` is 2, so the finished range is still a legal target and
    # the choice between the two is decided purely on depth - which is the comparison at issue.
    yard = Yard(
        [_site(10, under_construction=True), _site(12)],
        queues={10: 0, 12: 1},
    )
    picked = yard.next_recruit()

    assert picked is not None
    unit, building = picked
    assert unit == ARCHERS
    assert building.object_id == 12


def test_a_finished_building_is_still_a_producer() -> None:
    """The gate narrows the list; it must not empty it."""
    yard = Yard([_site(12)])
    assert yard.producers() == {ARCHERS: [yard._sites[0]]}
