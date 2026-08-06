"""Not ordering a battalion the command-point ceiling has no room for.

The engine refuses an over-cap recruit the same silent way it refuses an unaffordable one - the
stream takes the order, logic discards it, nothing is reported - so the cost of asking is a
selection and a confirmation window every time. The old guard only asked whether headroom was
gone *outright*, which is true only at exactly the cap, while a battalion charges 12 to 60 points
and an elite horde more.

Measured across one live match: 71 of 219 recruit orders discarded, at a mean of 46 free points
against 409 for the ones that queued, 99% of the failures under 150 - and 18 of them the same
`GondorRangerHorde` at the same archer range.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.recruiting import Recruiting

RANGERS = "GondorRangerHorde"


class Queue:
    """`stage_recruit` with the pick fixed and everything past the guard recorded."""

    stage_recruit = Recruiting.stage_recruit

    def __init__(self, free: int, cost: int) -> None:
        self.observation = SimpleNamespace(me=SimpleNamespace(command_points_free=free))
        self.statics = SimpleNamespace(command_point_cost=lambda name: cost)
        self.session = SimpleNamespace(confirm_queued=self._confirm, recruit=lambda unit: True)
        self.ordered: list[str] = []
        self.selected = 0

    def next_recruit(self):
        return (RANGERS, SimpleNamespace(object_id=663))

    def staple_recruit(self):
        return None

    def select(self, targets) -> bool:
        self.selected += 1
        return True

    def _confirm(self, act, object_id: int) -> bool:
        act()
        return True

    def _issue(self, label: str, act) -> bool:
        self.ordered.append(label)
        return True

    def _report(self, label: str, ok: bool, good: str, bad: str) -> bool:
        return ok


def test_a_battalion_too_big_for_the_headroom_is_not_ordered() -> None:
    """46 free against a 60-point horde: the band where every one of those discards lived."""
    queue = Queue(free=46, cost=60)
    said = queue.stage_recruit()

    assert said is not None and "waiting for ceiling" in said
    assert queue.ordered == []
    # Nothing was selected either - the selection is half of what a discarded order wasted, and
    # it also clobbers whatever the army had selected.
    assert queue.selected == 0


def test_a_battalion_that_fits_is_ordered() -> None:
    queue = Queue(free=409, cost=60)
    said = queue.stage_recruit()

    assert said == f"recruit {RANGERS} at 663"
    assert queue.ordered == ["recruit"]


def test_a_battalion_that_exactly_fits_is_ordered() -> None:
    """The boundary is "costs more than is free", not "costs as much as is free"."""
    queue = Queue(free=60, cost=60)
    assert queue.stage_recruit() == f"recruit {RANGERS} at 663"


def test_an_unpriced_template_is_never_refused_for_headroom() -> None:
    """`command_point_cost` answers 0 for a template the tree does not price, and 0 must mean
    "charges nothing" rather than "blocks everything"."""
    queue = Queue(free=1, cost=0)
    assert queue.stage_recruit() == f"recruit {RANGERS} at 663"


def test_a_cap_that_is_gone_outright_still_stops_everything() -> None:
    """The original guard, which the new one adds to rather than replaces."""
    queue = Queue(free=0, cost=60)
    assert queue.stage_recruit() is None
    assert queue.ordered == []
