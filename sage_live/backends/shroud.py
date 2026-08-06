"""Reading the engine's shroud grid out of a process.

The *model* - what a shroud level means, and how a world position becomes a cell - is
`sage_live.api.shroud`, along with the measurements that pin it down. This is only the byte
side: find `TheShroudManager`, walk its facade to the implementation object, and lift one `u16`
column per requested seat out of the cell array.

Kept apart from the model for the same reason every other reader is: the model is what a policy
reasons with and must import cleanly with no game, no Windows and no elevation, while this needs
an address table for one specific build.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from sage_live.api.shroud import MAX_SHROUD_PLAYERS, ShroudGrid
from sage_patch.addresses import (
    SHROUD_CELL_STRIDE,
    SHROUD_RECORD_BASE,
    SHROUD_RECORD_STRIDE,
)

__all__ = ["read_shroud"]

# A grid larger than this is a bad read rather than a big map. The measured map is 104x104 with
# 40-unit cells, so this allows one some 80x larger by area before refusing.
_MAX_CELLS = 1 << 20


def read_shroud(
    read_u32: Callable[[int], int | None],
    read_f32: Callable[[int], float | None],
    read_bytes: Callable[[int, int], bytes | None],
    shroud_manager: int,
    impl_offset: int,
    field: Mapping[str, int],
    players: Iterable[int],
) -> ShroudGrid | None:
    """The grid for `players`, or None when there is no readable one.

    Takes accessors rather than a `MemorySource` so the caller keeps its own pointer validation
    and diagnostics; `MemoryBackend.read_shroud` is the only caller and supplies its own.

    None is the ordinary answer at the menu, where the grid collapses to 1x1 with no seats, and
    it is deliberately not a diagnostic. What would be wrong is returning an *empty* grid, which
    a filter cannot tell from one where nothing happens to be visible.
    """
    wrapper = read_u32(shroud_manager)
    if not wrapper:
        return None
    impl = read_u32(wrapper + impl_offset)
    if not impl:
        return None

    cells_x = read_u32(impl + field["cells_x"])
    cells_y = read_u32(impl + field["cells_y"])
    base = read_u32(impl + field["cells"])
    inv = read_f32(impl + field["inv_cell_size"])
    if not cells_x or not cells_y or not base or not inv:
        return None
    count = cells_x * cells_y
    if count > _MAX_CELLS:
        return None

    raw = read_bytes(base, count * SHROUD_CELL_STRIDE)
    if raw is None or len(raw) < count * SHROUD_CELL_STRIDE:
        return None

    # One strided slice per byte of the `u16` rather than a loop over cells: the level of cell
    # `i` for player `p` sits at `i * 0xA8 + 4 + p * 8`, so its low bytes are exactly
    # `raw[off::0xA8]`. On a 104x104 map that is two slices a seat instead of 10,816 unpacks.
    levels: dict[int, bytes] = {}
    for player in players:
        if not (0 <= player < MAX_SHROUD_PLAYERS) or player in levels:
            continue
        off = SHROUD_RECORD_BASE + player * SHROUD_RECORD_STRIDE
        low = raw[off::SHROUD_CELL_STRIDE][:count]
        high = raw[off + 1 :: SHROUD_CELL_STRIDE][:count]
        if len(low) < count or len(high) < count:
            continue
        column = bytearray(count * 2)
        column[0::2] = low
        column[1::2] = high
        levels[player] = bytes(column)

    fog = read_bytes(impl + field["fog_enabled"], 1)
    return ShroudGrid(
        origin=(
            read_f32(impl + field["origin_x"]) or 0.0,
            read_f32(impl + field["origin_y"]) or 0.0,
        ),
        cell_size=read_f32(impl + field["cell_size"]) or 0.0,
        inv_cell_size=inv,
        cells_x=cells_x,
        cells_y=cells_y,
        fog_enabled=bool(fog[0]) if fog else True,
        levels=levels,
    )
