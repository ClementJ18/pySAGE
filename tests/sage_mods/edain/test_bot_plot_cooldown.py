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

    def __init__(self, places: bool, unpacks: bool = False) -> None:
        self._outcomes = [places, unpacks]
        self._blocked_plots: dict[int, float] = {}
        self._cooldowns: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self.session = SimpleNamespace(
            build=lambda template, position: True, unpack=lambda template: True
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
    return SimpleNamespace(object_id=PLOT_ID, position=(100.0, 200.0, 0.0))


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
