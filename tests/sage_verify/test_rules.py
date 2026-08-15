"""Tests for the judgement itself.

Everything here is constructed: a grid with a hand-placed revealed patch, a handful of objects,
and one order. That is the point of keeping `rules` free of the game - the interesting cases
(a target seen once and walked away from, a sample taken a moment too late, fog switched off)
are all ones that are tedious to stage in a real match and trivial to state here.
"""

from __future__ import annotations

import struct

import pytest

from sage_live.api.shroud import ShroudGrid
from sage_verify.orders import OrderTarget
from sage_verify.rules import Memory, Snapshot, judge

CELLS = 8
CELL_SIZE = 40.0
ME, ENEMY, ALLY = 0, 1, 2


def grid(revealed: set[tuple[int, int]], *, player: int = ME, fog: bool = True) -> ShroudGrid:
    """A grid where `player` reveals exactly `revealed`, and the enemy reveals its own corner."""
    columns = {}
    for seat in (ME, ENEMY, ALLY):
        column = bytearray(CELLS * CELLS * 2)
        own = revealed if seat == player else {(CELLS - 1, CELLS - 1)}
        for cx, cy in own:
            struct.pack_into("<H", column, (cy * CELLS + cx) * 2, 1)
        columns[seat] = bytes(column)
    return ShroudGrid(
        origin=(0.0, 0.0),
        cell_size=CELL_SIZE,
        inv_cell_size=1.0 / CELL_SIZE,
        cells_x=CELLS,
        cells_y=CELLS,
        fog_enabled=fog,
        levels=columns,
    )


def at(cx: int, cy: int) -> tuple[float, float, float]:
    """The centre of a cell, in world coordinates."""
    return (cx * CELL_SIZE + CELL_SIZE / 2, cy * CELL_SIZE + CELL_SIZE / 2, 0.0)


def snapshot(
    frame: int = 100,
    *,
    revealed: set[tuple[int, int]] | None = None,
    objects: dict[int, tuple[tuple[float, float, float], int]] | None = None,
    fog: bool = True,
) -> Snapshot:
    return Snapshot(
        frame=frame,
        objects=objects if objects is not None else {},
        shroud=grid(revealed if revealed is not None else set(), fog=fog),
    )


def call(target: OrderTarget, **kwargs: object):
    defaults = dict(player=ME, frame=100, memory=Memory(), max_lag=30)
    defaults.update(kwargs)
    return judge(target, **defaults)  # type: ignore[arg-type]


class TestObjectTargets:
    def test_attacking_a_visible_enemy_is_fine(self) -> None:
        verdict = call(
            OrderTarget(object_id=7),
            snapshot=snapshot(revealed={(2, 2)}, objects={7: (at(2, 2), ENEMY)}),
        )
        assert verdict.outcome == "ok"

    def test_attacking_a_never_seen_enemy_is_a_violation(self) -> None:
        verdict = call(
            OrderTarget(object_id=7),
            snapshot=snapshot(revealed={(0, 0)}, objects={7: (at(5, 5), ENEMY)}),
        )
        assert verdict.outcome == "violation"
        assert verdict.confidence == "high"
        assert "never been observed to see" in verdict.reason

    def test_a_target_seen_earlier_and_now_hidden_is_fine(self) -> None:
        """The explored-versus-never-explored gap the engine does not keep. A player who scouted
        a building may attack it later, and calling that a violation would bury every real
        finding under them."""
        memory = Memory()
        memory.absorb(snapshot(frame=10, revealed={(5, 5)}, objects={7: (at(5, 5), ENEMY)}), [ME])
        verdict = call(
            OrderTarget(object_id=7),
            snapshot=snapshot(revealed={(0, 0)}, objects={7: (at(5, 5), ENEMY)}),
            memory=memory,
        )
        assert verdict.outcome == "ok"

    def test_own_objects_are_not_evidence(self) -> None:
        verdict = call(
            OrderTarget(object_id=7),
            snapshot=snapshot(revealed=set(), objects={7: (at(5, 5), ME)}),
        )
        assert verdict.outcome == "ok"

    def test_allied_objects_are_not_evidence(self) -> None:
        verdict = call(
            OrderTarget(object_id=7),
            snapshot=snapshot(revealed=set(), objects={7: (at(5, 5), ALLY)}),
            allies=[ALLY],
        )
        assert verdict.outcome == "ok"

    def test_an_object_absent_from_the_frame_is_unjudged(self) -> None:
        verdict = call(OrderTarget(object_id=7), snapshot=snapshot(revealed=set(), objects={}))
        assert verdict.outcome == "unjudged"


class TestPositionTargets:
    def test_targeting_revealed_ground_is_fine(self) -> None:
        verdict = call(OrderTarget(position=at(2, 2)), snapshot=snapshot(revealed={(2, 2)}))
        assert verdict.outcome == "ok"

    def test_targeting_never_revealed_ground_is_a_low_confidence_violation(self) -> None:
        """Ground can be aimed at for honest reasons, so this is circumstantial by construction
        and must never be reported at the same weight as an object target."""
        verdict = call(OrderTarget(position=at(6, 6)), snapshot=snapshot(revealed={(0, 0)}))
        assert verdict.outcome == "violation"
        assert verdict.confidence == "low"

    def test_ground_revealed_earlier_is_fine(self) -> None:
        memory = Memory()
        memory.absorb(snapshot(frame=10, revealed={(6, 6)}), [ME])
        verdict = call(
            OrderTarget(position=at(6, 6)),
            snapshot=snapshot(revealed={(0, 0)}),
            memory=memory,
        )
        assert verdict.outcome == "ok"


class TestRefusingToJudge:
    def test_no_sample_is_unjudged(self) -> None:
        assert call(OrderTarget(object_id=7), snapshot=None).outcome == "unjudged"

    def test_a_sample_from_after_the_order_is_refused(self) -> None:
        """Attacking a unit reveals it, so a later sample clears every real maphack. Judging from
        one would be worse than not judging at all."""
        verdict = call(
            OrderTarget(object_id=7),
            frame=100,
            snapshot=snapshot(frame=140, revealed={(5, 5)}, objects={7: (at(5, 5), ENEMY)}),
        )
        assert verdict.outcome == "unjudged"
        assert "after the order" in verdict.reason

    def test_a_stale_sample_is_refused(self) -> None:
        verdict = call(
            OrderTarget(object_id=7),
            frame=200,
            snapshot=snapshot(frame=100, revealed=set(), objects={7: (at(5, 5), ENEMY)}),
            max_lag=30,
        )
        assert verdict.outcome == "unjudged"
        assert "stale" in verdict.reason

    def test_fog_switched_off_is_unjudged_not_clean(self) -> None:
        """With fog off the grid is still maintained but the engine stops acting on it, so
        visibility says nothing about what a player knew."""
        verdict = call(
            OrderTarget(object_id=7),
            snapshot=snapshot(revealed=set(), objects={7: (at(5, 5), ENEMY)}, fog=False),
        )
        assert verdict.outcome == "unjudged"

    def test_a_missing_grid_is_unjudged(self) -> None:
        verdict = call(
            OrderTarget(object_id=7),
            snapshot=Snapshot(frame=100, objects={7: (at(5, 5), ENEMY)}, shroud=None),
        )
        assert verdict.outcome == "unjudged"


class TestMemory:
    def test_it_records_objects_and_cells_per_player(self) -> None:
        memory = Memory()
        memory.absorb(
            snapshot(frame=5, revealed={(1, 1), (1, 2)}, objects={7: (at(1, 1), ENEMY)}),
            [ME, ENEMY],
        )
        assert memory.has_seen_object(ME, 7)
        assert memory.has_seen_cell(ME, (1, 1))
        assert memory.has_seen_cell(ME, (1, 2))
        assert not memory.has_seen_cell(ME, (4, 4))
        # The enemy's own grid is its corner, so it has not seen the object at (1,1).
        assert not memory.has_seen_object(ENEMY, 7)

    def test_it_accumulates_across_samples(self) -> None:
        memory = Memory()
        memory.absorb(snapshot(frame=5, revealed={(1, 1)}), [ME])
        memory.absorb(snapshot(frame=9, revealed={(2, 2)}), [ME])
        assert memory.has_seen_cell(ME, (1, 1))
        assert memory.has_seen_cell(ME, (2, 2))
        assert memory.frame == 9

    def test_a_sample_with_no_grid_changes_nothing(self) -> None:
        memory = Memory()
        memory.absorb(Snapshot(frame=5, objects={}, shroud=None), [ME])
        assert memory.frame == -1


def test_untracked_seats_never_count_as_seen() -> None:
    """`0xFFFF` is "this seat has no shroud state", not "revealed" - reading it as a level would
    make every unused slot omniscient."""
    column = bytearray(CELLS * CELLS * 2)
    for index in range(CELLS * CELLS):
        struct.pack_into("<H", column, index * 2, 0xFFFF)
    untracked = ShroudGrid(
        origin=(0.0, 0.0),
        cell_size=CELL_SIZE,
        inv_cell_size=1.0 / CELL_SIZE,
        cells_x=CELLS,
        cells_y=CELLS,
        fog_enabled=True,
        levels={ME: bytes(column)},
    )
    memory = Memory()
    memory.absorb(Snapshot(frame=5, objects={7: (at(1, 1), ENEMY)}, shroud=untracked), [ME])
    assert not memory.has_seen_cell(ME, (1, 1))
    assert not memory.has_seen_object(ME, 7)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_position_does_not_raise(bad: float) -> None:
    """A live object table routinely carries one mid-spawn or mid-death, and `under_fog` walking
    every object is where that used to kill a run."""
    verdict = call(
        OrderTarget(object_id=7),
        snapshot=snapshot(revealed={(2, 2)}, objects={7: ((bad, bad, 0.0), ENEMY)}),
    )
    assert verdict.outcome == "violation"
