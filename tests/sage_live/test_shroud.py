"""The shroud grid and the fog filter built on it.

Two halves, tested apart: `read_shroud` turns bytes into a `ShroudGrid` and must survive a
menu-shaped read, and `ShroudGrid` / `Observation.under_fog` decide what a seat can see. The
byte fixtures are built to the layout in `sage_live.api.shroud`, so a change to the stride or
the record base breaks these rather than silently reading the wrong half of a cell.
"""

from __future__ import annotations

import struct

import pytest

from sage_live.api.observation import GameObject, Observation, PlayerState
from sage_live.api.shroud import MAX_SHROUD_PLAYERS, CellShroud, ShroudGrid
from sage_live.backends.shroud import read_shroud
from sage_patch.addresses import (
    SHROUD_CELL_STRIDE,
    SHROUD_RECORD_BASE,
    SHROUD_RECORD_STRIDE,
)

CELLS_X = CELLS_Y = 4
CELL_SIZE = 40.0


def grid_of(levels: dict[int, dict[tuple[int, int], int]], **kwargs) -> ShroudGrid:
    """A `ShroudGrid` from `{player: {(cx, cy): level}}`, everything else zero."""
    columns = {}
    for player, cells in levels.items():
        column = bytearray(CELLS_X * CELLS_Y * 2)
        for (cx, cy), value in cells.items():
            struct.pack_into("<H", column, (CELLS_X * cy + cx) * 2, value)
        columns[player] = bytes(column)
    return ShroudGrid(
        origin=kwargs.pop("origin", (0.0, 0.0)),
        cell_size=CELL_SIZE,
        inv_cell_size=1.0 / CELL_SIZE,
        cells_x=CELLS_X,
        cells_y=CELLS_Y,
        fog_enabled=kwargs.pop("fog_enabled", True),
        levels=columns,
    )


def test_level_is_a_count_not_a_flag():
    """Any positive count is CLEAR; the engine reads it as "how many things reveal this"."""
    grid = grid_of({3: {(0, 0): 1, (1, 0): 9, (2, 0): 0}})
    assert grid.status_at_cell(0, 0, 3) is CellShroud.CLEAR
    assert grid.status_at_cell(1, 0, 3) is CellShroud.CLEAR
    assert grid.status_at_cell(2, 0, 3) is CellShroud.HIDDEN


def test_ffff_is_untracked_not_shrouded():
    """0xFFFF marks a seat with no shroud state, which is not "never explored".

    The distinction is the module docstring's central measurement: in a live match the sentinel
    filled the grid for every *unused* seat and never appeared for a playing one.
    """
    grid = grid_of({3: {(0, 0): 0xFFFF}})
    assert grid.status_at_cell(0, 0, 3) is CellShroud.UNTRACKED
    assert not grid.visible((10.0, 10.0, 0.0), 3)


@pytest.mark.parametrize("player", [-1, MAX_SHROUD_PLAYERS, 999])
def test_player_index_outside_the_engines_bound_is_untracked(player):
    grid = grid_of({3: {(0, 0): 5}})
    assert grid.status_at_cell(0, 0, player) is CellShroud.UNTRACKED


def test_a_seat_that_was_not_read_is_untracked_rather_than_visible():
    """Absent is not the same as clear - a filter must not open up on a missing column."""
    grid = grid_of({3: {(0, 0): 5}})
    assert grid.status_at_cell(0, 0, 4) is CellShroud.UNTRACKED


def test_off_grid_is_untracked_in_both_directions():
    grid = grid_of({3: {(0, 0): 5}})
    assert grid.status((-1000.0, 0.0, 0.0), 3) is CellShroud.UNTRACKED
    assert grid.status((10_000.0, 0.0, 0.0), 3) is CellShroud.UNTRACKED


def test_cell_of_matches_the_engines_floor_and_origin():
    grid = grid_of({3: {}}, origin=(100.0, 200.0))
    assert grid.cell_of(100.0, 200.0) == (0, 0)
    assert grid.cell_of(139.9, 200.0) == (0, 0)
    assert grid.cell_of(140.0, 240.0) == (1, 1)
    # Below the origin floors negative rather than clamping, which is what makes the bounds
    # check in `status_at_cell` the thing that rejects it.
    assert grid.cell_of(60.0, 200.0) == (-1, 0)


def test_visible_cells_ignores_the_sentinel():
    grid = grid_of({3: {(0, 0): 2, (1, 0): 0xFFFF, (2, 0): 0}})
    assert grid.visible_cells(3) == 1
    assert grid.visible_cells(7) == 0


# --- the filter -----------------------------------------------------------------------


def unit(object_id: int, owner: int, position: tuple[float, float, float]) -> GameObject:
    return GameObject(
        object_id=object_id,
        template_name="GondorFighter",
        template_side="Men",
        position=position,
        angle=0.0,
        health=1.0,
        max_health=1.0,
        owner_index=owner,
    )


def observation_of(grid: ShroudGrid | None, *objects: GameObject) -> Observation:
    return Observation(
        frame=1,
        local_player=3,
        players=(
            PlayerState(index=3, name="me", faction="Men", resources=0),
            PlayerState(index=4, name="foe", faction="Isengard", resources=0),
        ),
        objects=objects,
        shroud=grid,
    )


def test_under_fog_hides_the_enemy_and_keeps_my_own():
    grid = grid_of({3: {(0, 0): 1}})
    mine_seen = unit(1, 3, (10.0, 10.0, 0.0))
    mine_unseen = unit(2, 3, (150.0, 150.0, 0.0))
    foe_seen = unit(3, 4, (20.0, 20.0, 0.0))
    foe_unseen = unit(4, 4, (150.0, 150.0, 0.0))

    got = observation_of(grid, mine_seen, mine_unseen, foe_seen, foe_unseen).under_fog()

    assert got.fogged is True
    assert [o.object_id for o in got.objects] == [1, 2, 3]


def test_under_fog_can_drop_own_objects_too():
    grid = grid_of({3: {(0, 0): 1}})
    got = observation_of(grid, unit(1, 3, (150.0, 150.0, 0.0))).under_fog(keep_own=False)
    assert got.objects == ()


def test_under_fog_takes_a_viewer_and_the_result_mirrors():
    """The property that proved the field live: each seat sees its own and not the other's."""
    grid = grid_of({3: {(0, 0): 1}, 4: {(3, 3): 1}})
    mine = unit(1, 3, (10.0, 10.0, 0.0))
    theirs = unit(2, 4, (130.0, 130.0, 0.0))
    obs = observation_of(grid, mine, theirs)

    assert [o.object_id for o in obs.under_fog(viewer=3, keep_own=False).objects] == [1]
    assert [o.object_id for o in obs.under_fog(viewer=4, keep_own=False).objects] == [2]


def test_no_grid_leaves_the_observation_alone():
    """Refusing to filter beats filtering with nothing - the latter blanks the map."""
    obs = observation_of(None, unit(1, 4, (999.0, 999.0, 0.0)))
    got = obs.under_fog()
    assert got is obs
    assert got.fogged is False


def test_fog_switched_off_in_the_match_leaves_the_observation_alone():
    grid = grid_of({3: {}}, fog_enabled=False)
    obs = observation_of(grid, unit(1, 4, (999.0, 999.0, 0.0)))
    assert obs.under_fog() is obs
    assert obs.under_fog().fogged is False


def test_under_fog_keeps_the_grid_so_scouting_can_still_be_reasoned_about():
    grid = grid_of({3: {(0, 0): 1}})
    got = observation_of(grid, unit(1, 3, (10.0, 10.0, 0.0))).under_fog()
    assert got.shroud is grid


# --- reading it out of bytes ----------------------------------------------------------


def build_process(levels: dict[int, dict[tuple[int, int], int]]) -> tuple[dict, dict]:
    """A fake process: `{address -> u32}` and `{address -> bytes}` for the reader's accessors."""
    wrapper, impl, cells = 0x1000, 0x2000, 0x3000
    raw = bytearray(CELLS_X * CELLS_Y * SHROUD_CELL_STRIDE)
    for player, mapping in levels.items():
        for (cx, cy), value in mapping.items():
            index = CELLS_X * cy + cx
            struct.pack_into(
                "<H",
                raw,
                index * SHROUD_CELL_STRIDE + SHROUD_RECORD_BASE + player * SHROUD_RECORD_STRIDE,
                value,
            )
    words = {
        0xDE4358: wrapper,
        wrapper + 0x10: impl,
        impl + 0x24: CELLS_X,
        impl + 0x28: CELLS_Y,
        impl + 0x2C: cells,
    }
    floats = {
        impl + 0x04: 0.0,
        impl + 0x08: 0.0,
        impl + 0x1C: CELL_SIZE,
        impl + 0x20: 1 / CELL_SIZE,
    }
    blocks = {(cells, len(raw)): bytes(raw), (impl + 0x68, 1): b"\x01"}
    return {"words": words, "floats": floats, "blocks": blocks}, {
        "origin_x": 0x04,
        "origin_y": 0x08,
        "cell_size": 0x1C,
        "inv_cell_size": 0x20,
        "cells_x": 0x24,
        "cells_y": 0x28,
        "cells": 0x2C,
        "fog_enabled": 0x68,
    }


def reader_for(process):
    return (
        lambda a: process["words"].get(a),
        lambda a: process["floats"].get(a),
        lambda a, n: process["blocks"].get((a, n)),
    )


def test_read_shroud_lifts_one_column_per_seat():
    process, field = build_process({3: {(1, 1): 4}, 4: {(2, 2): 7}})
    u32, f32, blob = reader_for(process)

    grid = read_shroud(u32, f32, blob, 0xDE4358, 0x10, field, [3, 4])

    assert grid is not None
    assert (grid.cells_x, grid.cells_y) == (CELLS_X, CELLS_Y)
    assert grid.fog_enabled is True
    assert sorted(grid.levels) == [3, 4]
    # Each seat's level lands only in its own column - the whole point of the strided lift.
    assert grid.level(1, 1, 3) == 4
    assert grid.level(1, 1, 4) == 0
    assert grid.level(2, 2, 4) == 7
    assert grid.level(2, 2, 3) == 0


def test_read_shroud_skips_seats_outside_the_engines_bound():
    process, field = build_process({3: {(0, 0): 1}})
    u32, f32, blob = reader_for(process)
    grid = read_shroud(u32, f32, blob, 0xDE4358, 0x10, field, [3, -1, 20, 3])
    assert grid is not None
    assert sorted(grid.levels) == [3]


@pytest.mark.parametrize("missing", ["wrapper", "impl", "cells", "raw"])
def test_read_shroud_returns_none_rather_than_an_empty_grid(missing):
    """The menu answer. An empty grid would read as "nothing is visible anywhere"."""
    process, field = build_process({3: {(0, 0): 1}})
    u32, f32, blob = reader_for(process)
    if missing == "wrapper":
        process["words"][0xDE4358] = 0
    elif missing == "impl":
        process["words"][0x1000 + 0x10] = 0
    elif missing == "cells":
        process["words"][0x2000 + 0x2C] = 0
    else:
        process["blocks"].clear()
    assert read_shroud(u32, f32, blob, 0xDE4358, 0x10, field, [3]) is None


def test_a_position_that_is_not_a_point_is_untracked() -> None:
    """A live object table carries these: something mid-spawn, mid-death or mid-teleport has
    `NaN` where its coordinates will be. `math.floor` raises on that, and because `under_fog`
    walks every object in the frame, one such object took down a whole run - the `ValueError`
    travelled out through `poll` and ended `Bot.run` from an object nothing had asked about."""
    grid = grid_of({3: {(0, 0): 1}})
    nan = float("nan")
    assert grid.status((nan, 0.0, 0.0), 3) is CellShroud.UNTRACKED
    assert grid.status((0.0, nan, 0.0), 3) is CellShroud.UNTRACKED
    assert grid.status((float("inf"), 0.0, 0.0), 3) is CellShroud.UNTRACKED


def test_an_unreadable_position_is_not_visible() -> None:
    """The safe direction for a filter: an object whose position cannot be read is dropped from
    the fogged view rather than acted on."""
    assert not grid_of({3: {(0, 0): 1}}).visible((float("nan"), float("nan"), 0.0), 3)
