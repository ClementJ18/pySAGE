"""Which subject the camera is given, and - mostly - when it refuses to change its mind.

The interesting behaviour here is all restraint. Every stage re-decides from scratch each cycle,
so a camera that simply pointed at the current best subject would cut on every tie and every
transient; at a two-second interval that is a slideshow of half-second shots. The dwell timer is
the whole feature, and it fails silently - a broken one still points the camera somewhere
plausible, and nothing in a log would say it was wrong.

**Getting there is not this file's job any more.** The director names a target and `CameraPan`
closes on it between cycles; easing one step per cycle was itself a jump every two seconds. See
`tests/sage_live/test_camera_pan.py` for the movement, and note that nothing here mentions zoom:
the director cannot write one, because `look_at` no longer goes through `View::setLocation`.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from sage_live.api.observation import Vec3
from sage_mods.edain.bot.director import Director, Shot
from sage_mods.edain.bot.tuning import SHOT_DWELL


class RecordingPan:
    """A `CameraPan` that records targets instead of writing them."""

    def __init__(self) -> None:
        self.aimed: list[Vec3] = []

    def aim(self, position: Vec3) -> None:
        self.aimed.append(position)


class Filming:
    """`stage_camera` over a supplied list of shots, with the target recorded rather than sent."""

    stage_camera = Director.stage_camera

    def __init__(self, shots: list[Shot], camera: bool = True) -> None:
        self.camera = camera
        self._shots = shots
        self._shot_label: str | None = None
        self._shot_since = 0.0
        self.pan = RecordingPan()
        self.session = SimpleNamespace()

    def shots(self) -> list[Shot]:
        return sorted(self._shots, key=lambda s: s.rank)


def _shot(x: float, rank: int, label: str, caption: str = "") -> Shot:
    return Shot((x, 0.0, 0.0), label, rank, caption)


def test_nothing_to_watch_moves_nothing() -> None:
    director = Filming([])
    assert director.stage_camera() is None
    assert director.pan.aimed == []


def test_the_best_subject_is_the_one_aimed_at() -> None:
    director = Filming([_shot(100.0, 3, "party 1"), _shot(900.0, 0, "the base")])
    said = director.stage_camera()
    assert director.pan.aimed == [(900.0, 0.0, 0.0)]
    assert said is not None and "the base" in said


def test_an_equal_ranked_rival_cannot_steal_the_shot() -> None:
    """The jitter this exists to prevent: two farms skirmishing, cutting between them forever."""
    director = Filming([_shot(0.0, 2, "party 1"), _shot(50.0, 2, "party 2")])
    director.stage_camera()
    first = director._shot_label
    for _ in range(5):
        director.stage_camera()
    assert director._shot_label == first


def test_a_more_important_subject_interrupts_immediately() -> None:
    """A dwell that outranked the base falling would be watching the wrong half of the match."""
    director = Filming([_shot(0.0, 3, "party 1")])
    director.stage_camera()
    assert director._shot_label == "party 1"
    director._shots.append(_shot(900.0, 0, "the base", "the base under siege"))
    director.stage_camera()
    assert director._shot_label == "the base"


def test_the_shot_is_released_once_the_dwell_expires() -> None:
    director = Filming([_shot(0.0, 3, "party 1"), _shot(50.0, 3, "party 2")])
    director.stage_camera()
    held = director._shot_label
    director._shot_since = time.monotonic() - SHOT_DWELL - 1.0
    director._shots = [_shot(50.0, 3, "party 2")]
    director.stage_camera()
    assert director._shot_label == "party 2" != held


def test_a_subject_that_dies_does_not_pin_the_camera() -> None:
    """A held label that is no longer offered must not keep the camera on empty ground."""
    director = Filming([_shot(0.0, 2, "party 1")])
    director.stage_camera()
    director._shots = [_shot(400.0, 3, "party 2")]
    director.stage_camera()
    assert director._shot_label == "party 2"


def test_a_moving_subject_is_re_aimed_every_cycle() -> None:
    """The pan needs a fresh target each cycle to follow a walking force; holding the shot is
    about identity, not about ceasing to say where it is."""
    director = Filming([_shot(0.0, 3, "party 1")])
    director.stage_camera()
    director._shots = [_shot(100.0, 3, "party 1")]
    director.stage_camera()
    assert director.pan.aimed == [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)]


def test_the_subjects_own_height_is_passed_through() -> None:
    """**Reversing an earlier fix, on evidence.**

    This once replaced the shot's Z with the live camera's, on the theory that `_centre` was
    handing the view the terrain's height instead of the camera's. Measured against a running
    match, that theory was wrong in a way that mattered: `ViewLocation.position` *is* the look-at
    point on the ground - a camera reporting z=150.00 sat over 137 objects whose median z was
    150.00 - and the camera's own altitude is derived from it. So the ground under the subject is
    exactly the right answer, and the zoom artefact that prompted the change came from somewhere
    else entirely (`View::setLocation` writing a zoom it cannot round-trip).
    """
    director = Filming([Shot((500.0, 600.0, 42.0), "party 0", 3)])
    director.stage_camera()
    assert director.pan.aimed == [(500.0, 600.0, 42.0)]


def test_a_subject_that_starts_fighting_keeps_its_shot() -> None:
    """The reported jump: the same force flickering in and out of contact, cutting every time.

    Encoding state into the label made `party 0 marching` and `party 0 fighting` two different
    subjects, so a force that had not moved was re-cut whenever an enemy drifted either side of
    the contact radius - which from outside is the camera jumping to the same place repeatedly.
    Identity has to survive a change of state.
    """
    director = Filming([_shot(100.0, 3, "party 0", "party 0 marching")])
    director.stage_camera()
    since = director._shot_since
    director._shots = [_shot(100.0, 2, "party 0", "party 0 fighting")]
    director.stage_camera()
    assert director._shot_label == "party 0"  # same subject, no cut
    assert director._shot_since == since  # and the dwell was not restarted


def test_the_caption_describes_and_the_label_identifies() -> None:
    director = Filming([_shot(0.0, 3, "party 0", "party 0 marching")])
    said = director.stage_camera()
    assert said == "camera: party 0 marching"
    assert director._shot_label == "party 0"


def test_a_shot_with_no_caption_prints_its_label() -> None:
    director = Filming([_shot(0.0, 4, "the army")])
    assert director.stage_camera() == "camera: the army"


def test_the_camera_can_be_switched_off_entirely() -> None:
    """`--no-camera` reaches the view, not just the reporting.

    The stage is gated rather than dropped from `decide`'s lists, so the thing worth pinning is
    that no target is set - a version that still moved the camera and only withheld the caption
    would take the view away from the watcher exactly as before.
    """
    director = Filming([Shot((500.0, 600.0, 42.0), "party 0", 3)], camera=False)
    assert director.stage_camera() is None
    assert director.pan.aimed == []
