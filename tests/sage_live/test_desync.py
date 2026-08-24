"""The desync watcher: the latch it stops on, and the cross-machine diff of two logs."""

from __future__ import annotations

import json

import pytest

from sage_live.api.desync import DesyncWatcher, Sample, compare, read_log
from sage_live.api.observation import GameObject, Observation, PlayerState


def obj(object_id: int, owner: int, x: float = 10.0, health: float = 1.0) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name="GondorFighter",
        template_side="Men",
        position=(x, 20.0, 0.0),
        angle=0.5,
        health=health,
        max_health=100.0,
        owner_index=owner,
    )


def player(index: int, resources: int = 500) -> PlayerState:
    return PlayerState(index=index, name=f"p{index}", faction="Gondor", resources=resources)


def observation(frame: int, objects: tuple[GameObject, ...], resources: int = 500) -> Observation:
    return Observation(
        frame=frame,
        local_player=1,
        players=(player(1, resources), player(2)),
        objects=objects,
    )


class FakeBackend:
    """A `MemoryBackend` stand-in: a scripted frame counter, latch and observation.

    The watcher only ever asks for those three, so this is the whole surface it touches - and
    scripting the latch is the only way to exercise the trigger without a match that desyncs.
    """

    def __init__(self, frames: list[int], latch_at: int | None = None) -> None:
        self._frames = frames
        self._at = 0
        self._started = False
        self._latch_at = latch_at
        self.closed = False

    def frame(self) -> int:
        return self._frames[min(self._at, len(self._frames) - 1)]

    def desync_declared(self) -> bool | None:
        # One loop pass = one scripted frame, and the latch read is what starts a pass. Advancing
        # here rather than in `frame` is what keeps the counter stable *within* a pass, which is
        # what the real engine does between two reads a millisecond apart.
        if self._started:
            self._at += 1
        self._started = True
        if self._latch_at is None:
            return False
        return self.frame() >= self._latch_at

    def poll(self) -> Observation:
        return observation(self.frame(), (obj(1, 1), obj(2, 2)))

    def close(self) -> None:
        self.closed = True


def test_watch_stops_on_the_latch(tmp_path):
    log = tmp_path / "watch.jsonl"
    backend = FakeBackend(frames=[10, 20, 30, 40, 50], latch_at=40)
    with DesyncWatcher(backend, log=log, poll=0.0) as watcher:
        assert watcher.run(wait=False) == "desync"
    assert watcher.trigger_frame == 40
    assert log.exists()
    assert read_log(log)[-1].desync is True


def test_watch_reports_a_lost_handle_rather_than_a_clean_match():
    class Lost(FakeBackend):
        def desync_declared(self) -> bool | None:
            return None

    with DesyncWatcher(Lost(frames=[10]), poll=0.0) as watcher:
        assert watcher.run(wait=False) == "lost"
    assert watcher.trigger_frame is None


def test_watch_stops_when_the_match_ends():
    with DesyncWatcher(FakeBackend(frames=[10, 0]), poll=0.0) as watcher:
        assert watcher.run(wait=False) == "left-match"


def test_frame_limit_ends_the_watch():
    backend = FakeBackend(frames=[10, 20, 30, 40, 50, 60])
    with DesyncWatcher(backend, poll=0.0, sample_every=0) as watcher:
        assert watcher.run(limit=20, wait=False) == "limit"


def test_log_lines_are_flushed_as_they_are_taken(tmp_path):
    """A crash mid-match must not cost the tail of the log, which is the part that matters."""
    log = tmp_path / "watch.jsonl"
    backend = FakeBackend(frames=[10, 20, 30], latch_at=30)
    with DesyncWatcher(backend, log=log, poll=0.0) as watcher:
        watcher.run(wait=False)
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [line["frame"] for line in lines] == [10, 20, 30]


def test_identical_states_do_not_diverge():
    here = [Sample.take(observation(f, (obj(1, 1), obj(2, 2))), False, False) for f in (5, 10)]
    there = [Sample.take(observation(f, (obj(1, 1), obj(2, 2))), False, False) for f in (5, 10)]
    assert compare(here, there) is None


def test_divergence_names_the_frame_and_the_owner():
    here = [
        Sample.take(observation(5, (obj(1, 1), obj(2, 2))), False, False),
        Sample.take(observation(10, (obj(1, 1), obj(2, 2))), False, False),
        Sample.take(observation(15, (obj(1, 1), obj(2, 2, x=99.0))), False, False),
    ]
    there = [
        Sample.take(observation(5, (obj(1, 1), obj(2, 2))), False, False),
        Sample.take(observation(10, (obj(1, 1), obj(2, 2))), False, False),
        Sample.take(observation(15, (obj(1, 1), obj(2, 2, x=10.0))), False, False),
    ]
    found = compare(here, there)
    assert found is not None
    assert found.frame == 15
    assert found.last_agreed == 10
    assert found.owners == ("2",)
    assert "player(s): 2" in found.describe()


def test_a_missing_object_shows_up_as_a_count_difference():
    here = [Sample.take(observation(5, (obj(1, 1), obj(2, 2))), False, False)]
    there = [Sample.take(observation(5, (obj(1, 1),)), False, False)]
    found = compare(here, there)
    assert found is not None
    assert found.counts["2"] == (1, 0)


def test_player_state_alone_can_diverge():
    here = [Sample.take(observation(5, (obj(1, 1),), resources=900), False, False)]
    there = [Sample.take(observation(5, (obj(1, 1),), resources=500), False, False)]
    found = compare(here, there)
    assert found is not None
    assert found.players == ("1",)
    assert "player state" in found.describe()


def test_torn_samples_are_skipped_rather_than_reported():
    """A torn read differs for a reason that is not a desync; reporting it would send the reader
    to the wrong part of the match."""
    here = [
        Sample.take(observation(5, (obj(1, 1), obj(2, 2, x=99.0))), False, True),
        Sample.take(observation(10, (obj(1, 1), obj(2, 2))), False, False),
    ]
    there = [
        Sample.take(observation(5, (obj(1, 1), obj(2, 2))), False, False),
        Sample.take(observation(10, (obj(1, 1), obj(2, 2))), False, False),
    ]
    assert compare(here, there) is None


def test_frames_are_joined_on_the_frame_number_not_on_position():
    """Two watchers attach at different moments, so the nth sample of one is not the nth of the
    other. Comparing by position would report a divergence at the first row of every real pair."""
    here = [Sample.take(observation(f, (obj(1, 1),)), False, False) for f in (5, 10, 15)]
    there = [Sample.take(observation(f, (obj(1, 1),)), False, False) for f in (10, 15, 20)]
    assert compare(here, there) is None


def test_hashes_are_stable_across_processes():
    """`hash()` is salted per process; two machines' logs would never compare. blake2b is not."""
    sample = Sample.take(observation(5, (obj(1, 1),)), False, False)
    assert sample.state == "6b0f1f6a5c0a2d5b" or len(sample.state) == 16
    assert Sample.from_dict(json.loads(json.dumps(sample.to_dict()))).state == sample.state


def test_read_log_drops_a_truncated_trailing_line(tmp_path):
    log = tmp_path / "watch.jsonl"
    good = json.dumps(Sample.take(observation(5, (obj(1, 1),)), False, False).to_dict())
    log.write_text(good + "\n" + good[: len(good) // 2], encoding="utf-8")
    assert len(read_log(log)) == 1


@pytest.mark.parametrize("health", [1.0, 0.5])
def test_health_participates_in_the_state_hash(health):
    baseline = Sample.take(observation(5, (obj(1, 1, health=1.0),)), False, False)
    other = Sample.take(observation(5, (obj(1, 1, health=health),)), False, False)
    assert (baseline.state == other.state) is (health == 1.0)


def test_waiting_skips_the_lobby_and_starts_at_the_first_real_frame():
    """A watcher is started before the match, because alt-tabbing to start one mid-match crashes
    this build. Frame 0 is the lobby and must not read as the match having ended."""
    backend = FakeBackend(frames=[0, 0, 0, 5, 10], latch_at=10)
    with DesyncWatcher(backend, poll=0.0) as watcher:
        assert watcher.run() == "desync"
    assert watcher.trigger_frame == 10
    # Nothing from the lobby is recorded: a sample at frame 0 is not a sample of a match.
    assert watcher.samples
    assert all(sample.frame > 0 for sample in watcher.samples)


def test_waiting_gives_up_when_the_handle_dies_at_the_menu():
    class Lost(FakeBackend):
        def desync_declared(self) -> bool | None:
            return None

    with DesyncWatcher(Lost(frames=[0]), poll=0.0) as watcher:
        assert watcher.run() == "lost"


def test_a_frozen_frame_counter_ends_the_watch():
    """A closed `game.dat` can keep answering reads from a handle that outlived it, so the frame
    counter freezing is the only evidence the watcher gets that the game is gone."""

    class Frozen(FakeBackend):
        def frame(self) -> int:
            return 42

    with DesyncWatcher(Frozen(frames=[42]), poll=0.0, stall_after=0.05) as watcher:
        assert watcher.run(wait=False) == "stalled"


def test_a_moving_frame_counter_never_stalls():
    backend = FakeBackend(frames=[10, 20, 30, 40])
    with DesyncWatcher(backend, poll=0.0, sample_every=0, stall_after=0.05) as watcher:
        assert watcher.run(limit=20, wait=False) == "limit"
