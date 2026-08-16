"""How big the base is, and why almost every economy decision is really that question.

A castle start and a camp start differ by several plots, and `ECONOMY_CAP` cannot tell them
apart: it says a seventh house buys no further discount, which is true of every base, while
saying nothing about a base with five plots whose plan still wants a stable and a marketplace.
Capped alone the economy wants twelve plots for Men, sits ahead of research in
`wanted_buildings`, and takes every plot a small base has.

The measurement has one trap and it is expensive: `wait_for_match` returns at frame 0 with the
map still spawning, so the first cycles see no base at all. Measured live, the status line sat at
`plots 0` for the opening cycles of both runs of a session. A reading taken once at cycle 1 is
therefore zero, and a reading taken fresh every cycle shrinks under siege - so the honest answer
is a high-water mark.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.economy import Economy
from sage_mods.edain.bot.tuning import BASE_RADIUS, ECONOMY_CAP
from sage_mods.edain.bot.world import World

PLOT = "GondorBuildingFoundation"
FLAG = "WirtschaftPlotFlag_Real"


def _plot(object_id: int, template: str = PLOT, x: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        template_name=template,
        position=(x, 0.0, 0.0),
        distance_to=lambda other, _x=x: abs(other[0] - _x),
    )


class Base:
    """`base_plots` and `base_capacity` over a base placed by hand."""

    base_plots = World.base_plots
    base_capacity = World.base_capacity

    def __init__(self, owned: list) -> None:
        self._base_capacity = 0
        self.observation = SimpleNamespace(mine=owned)
        self.statics = SimpleNamespace(
            is_build_site=lambda name: name in (PLOT, FLAG),
            unpack_buttons=lambda name: (name,) if name == FLAG else (),
        )

    def base_centre(self) -> tuple[float, float, float]:
        return (0.0, 0.0, 0.0)

    def see(self, owned: list) -> None:
        self.observation = SimpleNamespace(mine=owned)


def test_an_occupied_plot_is_still_one_of_the_bases_plots() -> None:
    """The filter `free_plots` needs and this one must not have. A base is not smaller for
    having been built on, and reading it that way would shrink the plan as the base fills."""
    base = Base([_plot(1), _plot(2), _plot(3)])
    assert base.base_capacity() == 3


def test_an_external_flag_is_not_a_base_plot() -> None:
    """A settlement flag is a build site too, and it is somebody's expansion rather than part of
    the castle - `stage_expand`'s job, not the economy's."""
    base = Base([_plot(1), _plot(2, FLAG, x=50.0)])
    assert base.base_capacity() == 1


def test_a_captured_castle_across_the_map_does_not_grow_the_base() -> None:
    """`free_plots` drops the radius on purpose so a claimed camp's plots get built on. Here the
    radius is the point: this is the base the match dealt, not a running total of conquest."""
    base = Base([_plot(1), _plot(2), _plot(9, x=BASE_RADIUS * 4)])
    assert base.base_capacity() == 2


def test_the_unspawned_base_does_not_become_the_answer() -> None:
    """**The expensive trap.** Frame 0 arrives before the map has finished spawning, so a
    reading taken once at cycle 1 is zero - and a zero capacity would budget the economy out of
    its first farm."""
    base = Base([])
    assert base.base_capacity() == 0

    base.see([_plot(1), _plot(2), _plot(3), _plot(4)])
    assert base.base_capacity() == 4


def test_a_base_under_siege_does_not_report_itself_smaller() -> None:
    """The other direction. Plots are destroyed and rebuilt, and an economy that re-planned
    around the damage would rebuild its whole shape every time a house came down."""
    base = Base([_plot(1), _plot(2), _plot(3)])
    assert base.base_capacity() == 3

    base.see([_plot(1)])
    assert base.base_capacity() == 3


class Plan:
    """`economy_room` over a plan whose targets and standing buildings are set by hand."""

    economy_room = Economy.economy_room

    def __init__(self, capacity: int, standing: tuple[str, ...] = ()) -> None:
        self._capacity = capacity
        self._standing = standing
        self.plan = SimpleNamespace(
            production=("Barracks", "ArcherRange", "Stable"),
            production_target=3,
            research=("MarketPlace", "Forge"),
            resource="Wohnhaus",
            economy=("Forge2",),
        )

    def base_capacity(self) -> int:
        return self._capacity

    def economy_set(self) -> tuple[str, ...]:
        return (self.plan.resource, *self.plan.economy)

    def owned_building(self, template: str) -> list:
        return [object()] * self._standing.count(template)

    def missing_research(self) -> list[str]:
        return [b for b in self.plan.research if b not in self._standing]


def test_the_economy_budget_leaves_room_for_what_the_plan_still_wants() -> None:
    """Nine plots, three production buildings and two research centres outstanding - so four
    plots are the economy's and the other five are spoken for."""
    assert Plan(capacity=9).economy_room() == 4


def test_the_reservation_lifts_as_the_plan_completes() -> None:
    """**A reserve that never lifts starves the income that pays for everything**, which is the
    deadlock `held_for_research` records from the other side."""
    built = ("Barracks", "ArcherRange", "Stable", "MarketPlace", "Forge")
    assert Plan(capacity=9, standing=built).economy_room() == 9


def test_a_small_base_still_gets_one_economy_building() -> None:
    """A base whose plan wants more buildings than it has plots must not budget the economy down
    to nothing - income is what makes any of the rest reachable."""
    assert Plan(capacity=2).economy_room() == 1


def test_an_unknown_capacity_does_not_budget_at_all() -> None:
    """Before the base spawns there is nothing to divide up, and refusing the opening's first
    farm on a reading of zero would be the worst possible time to be careful."""
    assert Plan(capacity=0).economy_room() == ECONOMY_CAP * 2
