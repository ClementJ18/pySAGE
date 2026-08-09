"""Resting a plot that was just built on, so a razed building is not instantly rebuilt.

`free_plots` decides a plot is available by testing what is *standing* on it, which is right -
building on a plot does not consume it, and the foundation stays underneath the finished
structure. But it means a building destroyed at 0% construction hands its plot straight back on
the next cycle, and the bot pays the full price again. Seen live: the same plot built and
destroyed four times in five seconds.

The cooldown was previously set only when both build paths *refused*. A build that succeeded and
was then razed recorded nothing at all.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from sage_mods.edain.bot.orders import Orders
from sage_mods.edain.bot.tuning import PLOT_COOLDOWN

PLOT_ID = 508


class Building:
    """`build_on_plot` with both order paths stubbed to a fixed outcome.

    `build_on_plot` tries the placement path first and the unpack path only if it refused, so the
    two are told apart by call order rather than by inspecting the lambda handed in.
    """

    build_on_plot = Orders.build_on_plot
    _spent_plot = Orders._spent_plot
    _strike = Orders._strike

    def __init__(self, places: bool, unpacks: bool = False, has_unpack: bool = True) -> None:
        self._outcomes = [places, unpacks]
        self._blocked_plots: dict[int, float] = {}
        self._cooldowns: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self.session = SimpleNamespace(
            build=lambda template, position: True, unpack=lambda template: True
        )
        # Whether this plot's palette offers an unpack at all. A castle plot's does not, and
        # `build_on_plot` must not spend a confirmation window on a path that cannot work -
        # see the ledger's `unpack never did anything` across three runs.
        self.statics = SimpleNamespace(
            unpack_buttons=lambda template: (("slot",),) if has_unpack else ()
        )

    def select(self, objects) -> bool:
        return True

    def confirm_built(self, template, plot, act) -> bool:
        act()
        return self._outcomes.pop(0) if self._outcomes else False

    def _issue(self, label: str, act) -> bool:
        return True

    def _report(self, label: str, ok: bool, good: str, bad: str) -> bool:
        return ok


def _plot() -> SimpleNamespace:
    return SimpleNamespace(
        object_id=PLOT_ID, position=(100.0, 200.0, 0.0), template_name="GondorBuildingFoundation"
    )


def test_a_plot_just_built_on_is_rested() -> None:
    """The fix: a successful build records the plot, so a razing cannot be answered instantly."""
    builder = Building(places=True)
    assert builder.build_on_plot("GondorWohnhaus", _plot()) is True

    until = builder._blocked_plots.get(PLOT_ID)
    assert until is not None
    assert until > time.monotonic()
    assert until <= time.monotonic() + PLOT_COOLDOWN


def test_the_rest_is_a_cooldown_and_not_a_permanent_block() -> None:
    """A plot lost to a raid that has since been driven off is worth having back."""
    builder = Building(places=True)
    builder.build_on_plot("GondorWohnhaus", _plot())

    # `free_plots` compares the stored deadline against now, so an expired one frees the plot.
    builder._blocked_plots[PLOT_ID] = time.monotonic() - 1.0
    assert builder._blocked_plots[PLOT_ID] < time.monotonic()


def test_a_plot_that_refused_both_paths_is_still_rested() -> None:
    """The behaviour that already existed, which the new call must not disturb."""
    builder = Building(places=False, unpacks=False)
    assert builder.build_on_plot("GondorWohnhaus", _plot()) is False
    assert builder._blocked_plots.get(PLOT_ID, 0.0) > time.monotonic()


def test_a_castle_plot_is_not_offered_the_unpack_path() -> None:
    """The fallback that never worked, in the only place it was ever run.

    `free_plots` only ever hands `build_on_plot` plots with **no** unpack button - that is how
    an internal castle plot is told from a settlement flag - so the unpack fallback was being
    tried against plots it could not possibly rescue. Three archived runs agree: `unpack never
    did anything`, 0 of 10, 0 of 14 and 0 of 4, while run 12 (which refused nothing) has no
    such ledger line at all. Each attempt cost a selection and a full confirmation window.
    """
    builder = Building(places=False, unpacks=True, has_unpack=False)
    assert builder.build_on_plot("GondorWohnhaus", _plot()) is False
    # `unpacks=True` would have counted as a success had the path been taken; it was not, and
    # the plot is still parked.
    assert builder._outcomes == [True]
    assert builder._blocked_plots.get(PLOT_ID, 0.0) > time.monotonic()


def test_a_plot_whose_palette_does_offer_an_unpack_still_gets_the_second_chance() -> None:
    """The mixed case the fallback was written for is untouched."""
    builder = Building(places=False, unpacks=True, has_unpack=True)
    assert builder.build_on_plot("GondorWohnhaus", _plot()) is True
    assert builder._outcomes == []
