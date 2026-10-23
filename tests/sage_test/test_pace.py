"""The pace summary, from hand-built samples - no game."""

from __future__ import annotations

import struct

import pytest
from sage_patch.addresses import GAME_ENGINE, GAME_ENGINE_MAX_FPS
from sage_test.pace import CLIENT_FRAMES_PER_SECOND, Sample, pace_to_client_rate, summarise


def steady(fps: float, seconds: float, ratio: int = 12) -> list[Sample]:
    """A game drawing exactly `fps`, simulating one logic frame every `ratio` client frames."""
    frames = int(fps * seconds)
    return [Sample(n / fps, 100 + n, 20 + n // ratio) for n in range(frames + 1)]


def test_a_steady_game_reports_its_rates():
    report = summarise(steady(60.0, 10.0), client_rate=60, logic_rate=5)
    assert report.client_fps == pytest.approx(60.0)
    assert report.logic_hz == pytest.approx(5.0, abs=0.01)
    assert report.sim_speed == pytest.approx(1.0, abs=0.01)
    assert report.frame_ms_p50 == pytest.approx(16.67, abs=0.01)
    assert report.fps_1pct_low == pytest.approx(60.0, abs=0.01)
    assert report.stall_share == 0.0


def test_a_missed_sample_is_not_a_slow_frame():
    """The poll skipping a frame shows as a two-frame gap; it is spread, not counted as one hitch."""
    samples = [s for s in steady(60.0, 1.0) if s.client_frame != 130]
    report = summarise(samples, 60, 5)
    assert report.frame_ms_max == pytest.approx(16.67, abs=0.01)


def test_a_hitch_shows_in_the_tail():
    samples = steady(60.0, 10.0)
    hitch = 300
    samples = samples[:hitch] + [
        Sample(s.t + 0.25, s.client_frame, s.logic_frame) for s in samples[hitch:]
    ]
    report = summarise(samples, 60, 5)
    assert report.frame_ms_max == pytest.approx(266.67, abs=0.1)
    assert report.frame_ms_p50 == pytest.approx(16.67, abs=0.01)
    assert report.fps_1pct_low < 60.0


def test_a_hitch_is_not_a_stall_but_a_frozen_second_is():
    samples = steady(30.0, 4.0)
    assert summarise(samples, 30, 5).stall_share == 0.0
    frozen = samples[:60] + [Sample(s.t + 1.0, s.client_frame, s.logic_frame) for s in samples[60:]]
    assert summarise(frozen, 30, 5).stall_share == pytest.approx(1.033 / 5.0, abs=0.01)


def test_one_sample_is_refused():
    with pytest.raises(ValueError, match="never advanced"):
        summarise(steady(30.0, 0.0), 30, 5)


class FakeProcess:
    def __init__(self, client_rate: int, cap: int) -> None:
        self.engine = 0x01000000
        self.memory = {
            CLIENT_FRAMES_PER_SECOND: client_rate,
            GAME_ENGINE: self.engine,
            self.engine + GAME_ENGINE_MAX_FPS: cap,
        }

    def read(self, address: int, size: int) -> bytes | None:
        value = self.memory.get(address)
        return struct.pack("<I", value) if value is not None else None

    def write(self, address: int, data: bytes) -> bool:
        self.memory[address] = struct.unpack("<I", data)[0]
        return True


def test_the_cap_follows_a_30_fps_binary_under_a_60_fps_mod():
    process = FakeProcess(client_rate=30, cap=60)
    assert pace_to_client_rate(process) == (60, 30)
    assert process.memory[process.engine + GAME_ENGINE_MAX_FPS] == 30


def test_a_cap_that_already_agrees_is_left_alone():
    process = FakeProcess(client_rate=60, cap=60)
    assert pace_to_client_rate(process) == (60, 60)
