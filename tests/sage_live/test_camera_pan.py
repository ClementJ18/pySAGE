"""`CameraPan` - closing on a target on its own clock.

**Why this is not just an ease helper.** A policy decides what is worth watching every couple of
seconds. Easing one step per decision is a jump every two seconds however small the step, which is
exactly what a viewer calls snapping - and it is what the bot did before this existed. Measured
against a running match, a quarter-second step read as snapping between locations and a 6ms one
read as a pan, so the rate is the feature and it cannot come from the policy's clock.

`_advance` is driven with an explicit time step throughout rather than by running the thread and
sleeping, so these are exact rather than timing-dependent. The thread is covered separately, for
the two things only it can get wrong: starting and stopping cleanly.
"""

from __future__ import annotations

import math

from sage_live.api.camera import PAN_CUT, PAN_SETTLED, PAN_TAU, CameraPan


class Aimed:
    """Records placements, and can refuse them."""

    def __init__(self, works: bool = True) -> None:
        self.works = works
        self.placed: list[tuple[float, float, float]] = []

    def look_at(self, position) -> bool:
        if self.works:
            self.placed.append(position)
        return self.works


def test_a_pan_with_no_target_writes_nothing() -> None:
    """Before the director has decided anything, the view belongs to whoever is at the keyboard."""
    view = Aimed()
    CameraPan(view)._advance(0.1)
    assert view.placed == []


def test_the_first_target_is_a_cut() -> None:
    """There is nothing to ease from, and easing from wherever the camera happens to be would
    drift across the map."""
    view = Aimed()
    pan = CameraPan(view)
    pan.aim((900.0, 700.0, 42.0))
    pan._advance(0.01)
    assert view.placed == [(900.0, 700.0, 42.0)]


def test_a_nearby_target_is_eased_toward_rather_than_jumped_to() -> None:
    view = Aimed()
    pan = CameraPan(view)
    pan.aim((0.0, 0.0, 0.0))
    pan._advance(0.01)
    pan.aim((100.0, 0.0, 0.0))
    pan._advance(PAN_TAU)
    # One time constant closes 1 - 1/e of the gap, and no more.
    assert math.isclose(view.placed[-1][0], 100.0 * (1.0 - math.exp(-1.0)), rel_tol=1e-6)


def test_the_ease_is_the_same_however_the_ticks_land() -> None:
    """**The reason the approach is exponential rather than a fixed fraction per tick.** Windows
    timer granularity makes the tick rate wander; a fraction-per-tick pan would speed up and slow
    down with it, which is visible. Splitting one step into ten must land in the same place.
    """
    whole, split = CameraPan(Aimed()), CameraPan(Aimed())
    for pan in (whole, split):
        pan.aim((0.0, 0.0, 0.0))
        pan._advance(0.01)
        pan.aim((100.0, 0.0, 0.0))
    whole._advance(0.1)
    for _ in range(10):
        split._advance(0.01)
    assert math.isclose(whole.at[0], split.at[0], rel_tol=1e-6)


def test_a_target_beyond_the_cut_distance_is_a_cut() -> None:
    """Easing across the map drifts through empty ground for seconds and reads as a fault."""
    view = Aimed()
    pan = CameraPan(view)
    pan.aim((0.0, 0.0, 0.0))
    pan._advance(0.01)
    far = (PAN_CUT + 500.0, 0.0, 0.0)
    pan.aim(far)
    pan._advance(0.01)
    assert view.placed[-1] == far


def test_an_arrived_pan_stops_writing() -> None:
    """**What leaves the keyboard usable.** A loop that kept rewriting an arrived camera would
    pin the view against anyone trying to move it, at 160 writes a second, forever.
    """
    view = Aimed()
    pan = CameraPan(view)
    pan.aim((0.0, 0.0, 0.0))
    for _ in range(200):
        pan._advance(0.01)
    settled = len(view.placed)
    assert settled < 200  # it stopped long before the ticks did
    for _ in range(50):
        pan._advance(0.01)
    assert len(view.placed) == settled


def test_arriving_is_a_distance_not_an_exact_match() -> None:
    """An exponential approach never exactly arrives, so 'settled' has to be a radius."""
    view = Aimed()
    pan = CameraPan(view)
    pan.aim((0.0, 0.0, 0.0))
    pan._advance(0.01)
    pan.aim((PAN_SETTLED / 2.0, 0.0, 0.0))
    placed = len(view.placed)
    pan._advance(0.01)
    assert len(view.placed) == placed  # inside the radius, so not worth a write


def test_a_placement_that_fails_is_not_remembered_as_progress() -> None:
    """No view yet, or no bridge, is ordinary. A pan that counted a refused write as movement
    would resume from a position the camera never reached, and arrive somewhere else."""
    view = Aimed(works=False)
    pan = CameraPan(view)
    pan.aim((500.0, 0.0, 0.0))
    pan._advance(0.01)
    assert pan.at is None


def test_the_thread_starts_stops_and_is_idempotent() -> None:
    """The only two things the thread itself can get wrong. Started twice must not leave a second
    one writing, and `stop` must actually join - a daemon still writing into a closing game is
    the failure worth preventing."""
    pan = CameraPan(Aimed())
    pan.start()
    first = pan._thread
    pan.start()
    assert pan._thread is first
    pan.stop()
    assert pan._thread is None
    assert not first.is_alive()


def test_the_pan_can_be_used_as_a_context_manager() -> None:
    view = Aimed()
    with CameraPan(view) as pan:
        pan.aim((10.0, 20.0, 30.0))
    assert pan._thread is None
