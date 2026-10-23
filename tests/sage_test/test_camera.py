"""The camera follower, against a fake mover and clock - no game."""

from __future__ import annotations

import math
import struct
import time

import pytest

from sage_patch.addresses.ui import THE_TACTICAL_VIEW, VIEW_POSITION_OFFSET
from sage_test.camera import CameraFollow, tactical_view_mover


class Recorder:
    def __init__(self, ok: bool = True) -> None:
        self.moves: list[tuple[float, float, float]] = []
        self.ok = ok

    def __call__(self, point) -> bool:
        self.moves.append(point)
        return self.ok


def test_the_first_step_jumps_to_the_aim():
    move = Recorder()
    follow = CameraFollow(move)
    follow.aim((10.0, 20.0, 150.0))
    follow.step(follow.clock())
    assert move.moves == [(10.0, 20.0, 150.0)]


def test_easing_follows_the_wall_clock_not_the_step_count():
    """Two half-steps land where one whole step does: a late tick catches up exactly."""
    one = CameraFollow(Recorder(), time_constant=1.0)
    two = CameraFollow(Recorder(), time_constant=1.0)
    for follow in (one, two):
        follow._aim, follow._aimed_at = (0.0, 0.0, 0.0), 0.0
        follow.step(0.0)
        follow._aim = (100.0, 0.0, 0.0)
    one.step(1.0)
    two.step(0.5)
    two.step(1.0)
    expected = 100.0 * (1.0 - math.exp(-1.0))
    assert one.current[0] == pytest.approx(expected)
    assert two.current[0] == pytest.approx(expected)


def test_between_aims_it_predicts_from_the_velocity_height_included():
    follow = CameraFollow(Recorder())
    follow._aim, follow._aimed_at = (0.0, 0.0, 100.0), 0.0
    follow._velocity = (10.0, 5.0, 2.0)
    assert follow.predicted(0.5) == pytest.approx((5.0, 2.5, 101.0))


def test_a_stale_velocity_does_not_run_away():
    follow = CameraFollow(Recorder())
    follow._aim, follow._aimed_at, follow._velocity = (0.0, 0.0, 0.0), 0.0, (10.0, 0.0, 0.0)
    assert follow.predicted(60.0)[0] == pytest.approx(15.0)


def test_the_thread_keeps_moving_the_camera_while_a_check_is_slow():
    move = Recorder()
    with CameraFollow(move, rate=500.0) as follow:
        follow.aim((0.0, 0.0, 0.0))

        def slow_check():
            time.sleep(0.1)
            return True, None

        assert follow.run_until(slow_check, every=0.0, timeout=5.0)
    assert len(move.moves) > 10


def test_run_until_reports_a_timeout():
    with CameraFollow(Recorder(), rate=500.0) as follow:
        assert not follow.run_until(lambda: (False, None), every=0.01, timeout=0.05)


def test_failed_writes_are_counted():
    follow = CameraFollow(Recorder(ok=False))
    follow.aim((1.0, 2.0, 3.0))
    follow.step(follow.clock())
    assert follow.failed_writes == 1


class FakeProcess:
    def __init__(self, view: int) -> None:
        self.view = view
        self.written: dict[int, bytes] = {}

    def read(self, address: int, size: int) -> bytes | None:
        return struct.pack("<I", self.view) if address == THE_TACTICAL_VIEW else None

    def write(self, address: int, data: bytes) -> bool:
        self.written[address] = data
        return True


def test_the_mover_writes_the_look_at_point_into_the_view():
    process = FakeProcess(0x05000000)
    assert tactical_view_mover(process)((1.0, 2.0, 3.0))
    expected = struct.pack("<fff", 1.0, 2.0, 3.0)
    assert process.written == {0x05000000 + VIEW_POSITION_OFFSET: expected}


def test_the_mover_refuses_before_there_is_a_view():
    assert not tactical_view_mover(FakeProcess(0))((1.0, 2.0, 3.0))
