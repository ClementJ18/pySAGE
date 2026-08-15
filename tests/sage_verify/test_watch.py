"""Tests for the live loop, driven off a scripted list of observations.

`Watcher` takes its `poll` as a parameter precisely so this is possible: the ordering rule it
exists to enforce - judge an order against the sample *before* it, never the one after - is
invisible in a real match and trivial to stage here. Two of these tests would each have looked
like a working tool in a live run while quietly clearing every cheat put in front of them.
"""

from __future__ import annotations

import struct
from datetime import datetime

import pytest

from sage_live.api.observation import GameObject, Observation, PlayerState
from sage_live.api.shroud import ShroudGrid
from sage_replay.replay import (
    Bfme2OrderType,
    Order,
    OrderArgument,
    OrderArgumentType,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotType,
    ReplayTimestamp,
)
from sage_verify.watch import SeatMap, Watcher

CELLS = 8
CELL_SIZE = 40.0
ME, ENEMY = 0, 1
FIRST_SLOT_NUMBER = 3  # ReplayFile.slot_index's offset for Bfme2

ATTACK_OBJECT = 0x425


def at(cx: int, cy: int) -> tuple[float, float, float]:
    return (cx * CELL_SIZE + CELL_SIZE / 2, cy * CELL_SIZE + CELL_SIZE / 2, 0.0)


def _grid(revealed: dict[int, set[tuple[int, int]]]) -> ShroudGrid:
    columns = {}
    for seat, cells in revealed.items():
        column = bytearray(CELLS * CELLS * 2)
        for cx, cy in cells:
            struct.pack_into("<H", column, (cy * CELLS + cx) * 2, 1)
        columns[seat] = bytes(column)
    return ShroudGrid(
        origin=(0.0, 0.0),
        cell_size=CELL_SIZE,
        inv_cell_size=1.0 / CELL_SIZE,
        cells_x=CELLS,
        cells_y=CELLS,
        fog_enabled=True,
        levels=columns,
    )


def _object(object_id: int, cell: tuple[int, int], owner: int) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name="TestThing",
        template_side="Test",
        position=at(*cell),
        angle=0.0,
        health=1.0,
        max_health=100.0,
        owner_index=owner,
    )


def observation(
    frame: int,
    *,
    revealed: dict[int, set[tuple[int, int]]],
    objects: list[GameObject],
) -> Observation:
    return Observation(
        frame=frame,
        local_player=ME,
        players=(
            PlayerState(index=ME, name="Attacker", faction="Men", resources=0),
            PlayerState(index=ENEMY, name="Defender", faction="Mordor", resources=0),
        ),
        objects=tuple(objects),
        shroud=_grid(revealed),
    )


def replay_with(chunks: list[ReplayChunk]) -> ReplayFile:
    metadata = ReplayMetadata(
        map_file="test",
        slots=[
            ReplaySlot(slot_type=ReplaySlotType.Human, human_name="Attacker", faction=1, team=0),
            ReplaySlot(slot_type=ReplaySlotType.Human, human_name="Defender", faction=2, team=1),
        ],
    )
    header = ReplayHeader(
        game_type=ReplayGameType.Bfme2,
        start_time=datetime(2026, 1, 1),
        end_time=datetime(2026, 1, 1, 0, 10),
        num_timecodes=3000,
        filename="test",
        timestamp=ReplayTimestamp(2026, 1, 4, 1, 0, 0, 0, 0),
        version="test",
        build_date="test",
        metadata=metadata,
    )
    return ReplayFile(header=header, chunks=chunks)


def attack(frame: int, target: int, slot: int = 0) -> ReplayChunk:
    number = slot + FIRST_SLOT_NUMBER
    order = Order(player_index=number - 1, order_type=ATTACK_OBJECT)
    order.arguments.append(OrderArgument(OrderArgumentType.ObjectId, target))
    return ReplayChunk(timecode=frame, order_type=ATTACK_OBJECT, number=number, order=order)


def run(replay: ReplayFile, frames: list[Observation], **kwargs: object):
    """Drive a whole watch off a fixed list of observations."""
    feed = iter(frames)

    def poll() -> Observation | None:
        return next(feed, frames[-1] if frames else None)

    watcher = Watcher(
        replay=replay,
        poll=poll,
        sleep=lambda _: None,
        clock=lambda: 0.0,
        **kwargs,  # type: ignore[arg-type]
    )
    return watcher.run()


class TestSeatMap:
    def test_it_matches_slots_to_live_seats_by_name(self) -> None:
        obs = observation(10, revealed={ME: set(), ENEMY: set()}, objects=[])
        seats = SeatMap.build(replay_with([]), obs)
        assert seats.by_slot == {0: ME, 1: ENEMY}
        assert seats.notes == []

    def test_an_unmatched_slot_is_noted_rather_than_guessed(self) -> None:
        """The two numbering spaces disagree, so an offset assumption would judge one player's
        orders against another player's vision - silently."""
        obs = observation(10, revealed={ME: set(), ENEMY: set()}, objects=[])
        replay = replay_with([])
        replay.header.metadata.players[1].human_name = "SomeoneElse"
        seats = SeatMap.build(replay, obs)
        assert seats.by_slot == {0: ME}
        assert "matched no live seat" in seats.notes[0]

    def test_an_observer_slot_is_never_mapped(self) -> None:
        obs = observation(10, revealed={ME: set(), ENEMY: set()}, objects=[])
        replay = replay_with([])
        replay.header.metadata.players[1].faction = ReplaySlot.OBSERVER_FACTION
        seats = SeatMap.build(replay, obs)
        assert 1 not in seats.by_slot


class TestWatcher:
    def test_it_flags_an_attack_on_a_never_seen_enemy(self) -> None:
        enemy = _object(77, (6, 6), ENEMY)
        frames = [
            observation(10, revealed={ME: {(0, 0)}, ENEMY: {(6, 6)}}, objects=[enemy]),
            observation(120, revealed={ME: {(0, 0)}, ENEMY: {(6, 6)}}, objects=[enemy]),
            observation(130, revealed={ME: {(0, 0)}, ENEMY: {(6, 6)}}, objects=[enemy]),
        ]
        report = run(replay_with([attack(100, 77)]), frames, max_lag=200)
        assert len(report.findings) == 1
        finding = report.findings[0]
        assert finding.player_name == "Attacker"
        assert finding.target_object == 77
        assert finding.confidence == "high"

    def test_it_clears_an_attack_on_a_visible_enemy(self) -> None:
        enemy = _object(77, (6, 6), ENEMY)
        frames = [
            observation(10, revealed={ME: {(6, 6)}, ENEMY: set()}, objects=[enemy]),
            observation(120, revealed={ME: {(6, 6)}, ENEMY: set()}, objects=[enemy]),
        ]
        report = run(replay_with([attack(100, 77)]), frames, max_lag=200)
        assert report.findings == []
        assert report.outcomes["ok"] == 1

    def test_it_judges_against_the_sample_before_the_order_not_after(self) -> None:
        """**The test that matters.** Attacking reveals the target, so the frame after any attack
        shows it plainly visible. A loop that judged against the nearest sample - or the latest -
        would clear every maphack in the corpus while looking like it worked."""
        enemy = _object(77, (6, 6), ENEMY)
        frames = [
            # before the order: the attacker sees nothing out there
            observation(90, revealed={ME: {(0, 0)}, ENEMY: set()}, objects=[enemy]),
            # after the order: the attack has revealed the target
            observation(110, revealed={ME: {(6, 6)}, ENEMY: set()}, objects=[enemy]),
            observation(120, revealed={ME: {(6, 6)}, ENEMY: set()}, objects=[enemy]),
        ]
        report = run(replay_with([attack(100, 77)]), frames, max_lag=200)
        assert len(report.findings) == 1, "judged against the post-order sample"

    def test_a_target_scouted_earlier_is_cleared(self) -> None:
        enemy = _object(77, (6, 6), ENEMY)
        frames = [
            observation(10, revealed={ME: {(6, 6)}, ENEMY: set()}, objects=[enemy]),
            observation(50, revealed={ME: {(0, 0)}, ENEMY: set()}, objects=[enemy]),
            observation(120, revealed={ME: {(0, 0)}, ENEMY: set()}, objects=[enemy]),
        ]
        report = run(replay_with([attack(100, 77)]), frames, max_lag=200)
        assert report.findings == []

    def test_a_stale_sample_refuses_rather_than_guesses(self) -> None:
        enemy = _object(77, (6, 6), ENEMY)
        frames = [
            observation(10, revealed={ME: {(0, 0)}, ENEMY: set()}, objects=[enemy]),
            observation(500, revealed={ME: {(0, 0)}, ENEMY: set()}, objects=[enemy]),
        ]
        report = run(replay_with([attack(400, 77)]), frames, max_lag=30)
        assert report.findings == []
        assert report.outcomes["unjudged"] == 1
        assert report.coverage == 0.0

    def test_orders_from_an_unmapped_slot_are_unjudged(self) -> None:
        enemy = _object(77, (6, 6), ENEMY)
        replay = replay_with([attack(100, 77, slot=1)])
        replay.header.metadata.players[1].human_name = "SomeoneElse"
        frames = [
            observation(10, revealed={ME: {(0, 0)}, ENEMY: set()}, objects=[enemy]),
            observation(120, revealed={ME: {(0, 0)}, ENEMY: set()}, objects=[enemy]),
        ]
        report = run(replay, frames, max_lag=200)
        assert report.findings == []
        assert report.outcomes["unjudged"] == 1
        assert any("SomeoneElse" in note for note in report.seat_notes)

    def test_heartbeats_and_markers_are_not_counted_as_orders(self) -> None:
        heartbeat = ReplayChunk(
            timecode=100,
            order_type=int(Bfme2OrderType.ChecksumHeartbeat),
            number=FIRST_SLOT_NUMBER,
            order=Order(player_index=ME, order_type=int(Bfme2OrderType.ChecksumHeartbeat)),
        )
        report = run(
            replay_with([heartbeat]),
            [observation(120, revealed={ME: set(), ENEMY: set()}, objects=[])],
        )
        assert report.orders_seen == 0
        assert report.targeted_orders == 0

    def test_coverage_reports_how_much_was_actually_checked(self) -> None:
        """A run that judged nothing must not read as a clean match."""
        enemy = _object(77, (6, 6), ENEMY)
        replay = replay_with([attack(100, 77), attack(4000, 77)])
        frames = [
            observation(10, revealed={ME: {(0, 0)}, ENEMY: set()}, objects=[enemy]),
            observation(120, revealed={ME: {(0, 0)}, ENEMY: set()}, objects=[enemy]),
        ]
        report = run(replay, frames, max_lag=200)
        assert report.targeted_orders == 2
        assert report.coverage == pytest.approx(0.5)
        assert "coverage" in report.summary()


def test_a_clean_run_with_low_coverage_says_so() -> None:
    report = run(
        replay_with([attack(4000, 77)]),
        [observation(10, revealed={ME: set(), ENEMY: set()}, objects=[])],
    )
    assert report.findings == []
    assert "not checked" in report.summary()
