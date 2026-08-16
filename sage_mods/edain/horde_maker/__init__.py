"""Edain horde maker: a horde's formation drawn on a grid instead of counted out by hand.

`formation.py` is the whole model - a horde as a flat list of `Slot`s at game coordinates, and
the `RankInfo` block of a `HordeContain` rendered from it or read back into it. `ui/` is a small
PyQt6 window over that: place the soldiers on a grid, get the block, paste an existing block back
in to see the shape it describes.
"""

from sage_mods.edain.horde_maker.formation import (
    SIZES_COMMENT,
    Slot,
    parse_formation,
    parse_sizes,
    render_formation,
)

__all__ = [
    "SIZES_COMMENT",
    "Slot",
    "parse_formation",
    "parse_sizes",
    "render_formation",
]
