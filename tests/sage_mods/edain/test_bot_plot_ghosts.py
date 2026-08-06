"""Where the claimable plots are, and why that one question is asked through the fog.

The game draws every settlement plot as a ghost from the first frame, so their placement is not
something fog hides from anyone. Reading them from the filtered snapshot instead cost a whole
match: `under_fog` keeps no memory of what was seen before, so plots were not merely hidden at
the start - they went back to being hidden every time the army looked away, `stage_expand` never
had a candidate, and the opening's army stood still while `map_control` reported `map 100%`.

The tests that matter here are therefore the boundary ones: the census reaches through the fog,
it never shrinks, it keeps growing until the map has finished spawning, and it does *not* drag
live state through with it.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.world import World

CIVILIAN = 9
MINE = 1


def _plot(object_id: int, owner: int | None = CIVILIAN, x: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        object_id=object_id,
        owner_index=owner,
        template_name="WirtschaftPlotFlag_Real",
        position=(x, 0.0, 0.0),
        distance_to=lambda other, x=x: abs(other[0] - x),
    )


class Board:
    """`plot_ghosts` and friends over a fogged view and an unfogged one that disagree."""

    plot_ghosts = World.plot_ghosts
    plots_now = World.plots_now
    map_flags = World.map_flags
    map_control = World.map_control
    occupied = World.occupied

    def __init__(self, seen: list, whole: list) -> None:
        self._ghosts = None
        self.statics = SimpleNamespace(unpack_buttons=lambda name: name.startswith("Wirtschaft"))
        self.observation = SimpleNamespace(objects=tuple(seen))
        self.session = SimpleNamespace(
            player_index=MINE,
            latest_unfogged=SimpleNamespace(objects=tuple(whole)),
        )

    def structures(self) -> list:
        return []


def test_the_census_reaches_through_the_fog() -> None:
    """The bug: the seat can see none of them, and the whole map has three."""
    board = Board(seen=[], whole=[_plot(1), _plot(2), _plot(3)])
    assert sorted(board.plot_ghosts()) == [1, 2, 3]
    assert len(board.plots_now()) == 3


def test_an_empty_first_reading_is_not_remembered() -> None:
    """`wait_for_match` returns before the map has spawned anything, and caching that empty
    census would leave the bot with no plots for the rest of the match."""
    board = Board(seen=[], whole=[])
    assert board.plot_ghosts() == {}

    board.session.latest_unfogged = SimpleNamespace(objects=(_plot(1),))
    assert sorted(board.plot_ghosts()) == [1]


def test_a_partial_first_reading_is_not_remembered_either() -> None:
    """The failure the empty-guard above did not catch, and the expensive one. Attaching at the
    menu means arriving at frame 0 with the map **still spawning**: some plots exist and the rest
    do not, which is not an empty census and reads as a complete one. Measured live - 16 claimable
    plots on the map, `flags 1` in the bot, and two matches whose ledgers read `unpack never did
    anything`."""
    board = Board(seen=[], whole=[_plot(1), _plot(2)])
    assert sorted(board.plot_ghosts()) == [1, 2]

    # The rest of the map finishes spawning a few cycles later.
    board.session.latest_unfogged = SimpleNamespace(objects=(_plot(1), _plot(2), _plot(3)))
    assert sorted(board.plot_ghosts()) == [1, 2, 3]


def test_the_census_never_shrinks() -> None:
    """Placement is static, so a later reading - fogged, or simply of a plot now out of sight -
    must not take one away. The union grows and settles; it does not track."""
    board = Board(seen=[], whole=[_plot(1), _plot(2)])
    board.plot_ghosts()
    board.session.latest_unfogged = SimpleNamespace(objects=())
    assert sorted(board.plot_ghosts()) == [1, 2]


def test_the_first_ghost_of_a_plot_is_the_one_kept() -> None:
    """Merging must not let a later reading overwrite placement with a staler view of the same
    id - `plots_now` is what refreshes state, and this half is placement only."""
    board = Board(seen=[], whole=[_plot(1, x=500.0)])
    board.plot_ghosts()
    board.session.latest_unfogged = SimpleNamespace(objects=(_plot(1, owner=MINE, x=999.0),))
    assert board.plot_ghosts()[1].position == (500.0, 0.0, 0.0)
    assert board.plot_ghosts()[1].owner_index == CIVILIAN


def test_a_visible_plot_is_read_live_and_a_hidden_one_falls_back_to_its_ghost() -> None:
    """Placement is censused, state is not: fog is still entitled to hide who owns what."""
    board = Board(seen=[], whole=[_plot(1), _plot(2)])
    board.plot_ghosts()
    # Plot 1 is now in sight and has been claimed; plot 2 is still unseen.
    board.observation = SimpleNamespace(objects=(_plot(1, owner=MINE),))
    now = {o.object_id: o for o in board.plots_now()}
    assert now[1].owner_index == MINE  # the live reading won
    assert now[2].owner_index == CIVILIAN  # the frame-0 ghost, which is all there is


def test_map_control_no_longer_reports_a_blind_hundred_percent() -> None:
    """The false triumph: no visible flags meant no denominator, which read as total control."""
    board = Board(seen=[], whole=[_plot(1), _plot(2), _plot(3), _plot(4)])
    assert board.map_control() == 0.0

    board.observation = SimpleNamespace(objects=(_plot(1, owner=MINE),))
    assert board.map_control() == 0.25


def test_a_map_with_no_claimable_flag_is_still_controlled() -> None:
    """The rule that made the bug invisible is correct on its own terms, and is kept."""
    assert Board(seen=[], whole=[]).map_control() == 1.0
